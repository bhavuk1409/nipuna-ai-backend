import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as elbv2 from 'aws-cdk-lib/aws-elasticloadbalancingv2';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';
import * as acm from 'aws-cdk-lib/aws-certificatemanager';

interface EcsStackProps extends cdk.StackProps {
  vpc: ec2.Vpc;
  apiRepo: ecr.Repository;
  workerRepo: ecr.Repository;
  databaseSecret: cdk.aws_secretsmanager.ISecret;
  databaseEndpoint: string;
  redisEndpoint: string;
  openSearchEndpoint: string;
  rdsSg: ec2.ISecurityGroup;
  redisSg: ec2.ISecurityGroup;
}

export class EcsStack extends cdk.Stack {
  public readonly clusterArn: string;
  public readonly apiServiceArn: string;
  public readonly workerServiceArn: string;

  constructor(scope: Construct, id: string, props: EcsStackProps) {
    super(scope, id, props);

    const isProd = this.node.tryGetContext('isProd');
    const certificateArn = this.node.tryGetContext('certificateArn');

    const cluster = new ecs.Cluster(this, 'NipunaCluster', {
      vpc: props.vpc,
      containerInsights: true,
    });
    this.clusterArn = cluster.clusterArn;

    const albSg = new ec2.SecurityGroup(this, 'AlbSg', {
      vpc: props.vpc,
      allowAllOutbound: true,
    });
    albSg.addIngressRule(ec2.Peer.anyIpv4(), ec2.Port.tcp(certificateArn ? 443 : 80));

    const ecsSg = new ec2.SecurityGroup(this, 'EcsSg', {
      vpc: props.vpc,
      allowAllOutbound: true,
    });
    ecsSg.addIngressRule(albSg, ec2.Port.tcp(8000));

    new ec2.CfnSecurityGroupIngress(this, 'RdsEcsIngress', {
      groupId: props.rdsSg.securityGroupId,
      sourceSecurityGroupId: ecsSg.securityGroupId,
      ipProtocol: 'tcp',
      fromPort: 5432,
      toPort: 5432,
    });

    new ec2.CfnSecurityGroupIngress(this, 'RedisEcsIngress', {
      groupId: props.redisSg.securityGroupId,
      sourceSecurityGroupId: ecsSg.securityGroupId,
      ipProtocol: 'tcp',
      fromPort: 6379,
      toPort: 6379,
    });

    const alb = new elbv2.ApplicationLoadBalancer(this, 'NipunaAlb', {
      vpc: props.vpc,
      internetFacing: true,
      securityGroup: albSg,
    });

    const listener = alb.addListener(certificateArn ? 'HttpsListener' : 'HttpListener', {
      port: certificateArn ? 443 : 80,
      protocol: certificateArn ? elbv2.ApplicationProtocol.HTTPS : elbv2.ApplicationProtocol.HTTP,
      certificates: certificateArn
        ? [acm.Certificate.fromCertificateArn(this, 'AlbCertificate', certificateArn)]
        : undefined,
    });

    const taskRole = new iam.Role(this, 'EcsTaskRole', {
      roleName: 'nipuna-ecs-task-role',
      assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AmazonECSTaskExecutionRolePolicy'),
      ],
    });

    taskRole.addToPolicy(new iam.PolicyStatement({
      actions: ['secretsmanager:GetSecretValue'],
      resources: ['*'],
    }));

    taskRole.addToPolicy(new iam.PolicyStatement({
      actions: ['opensearchserverless:*'],
      resources: ['*'],
    }));

    const executionRole = new iam.Role(this, 'EcsExecutionRole', {
      assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AmazonECSTaskExecutionRolePolicy'),
      ],
    });

    const apiTaskDef = new ecs.FargateTaskDefinition(this, 'ApiTaskDef', {
      cpu: 512,
      memoryLimitMiB: 1024,
      taskRole,
      executionRole,
      runtimePlatform: {
        cpuArchitecture: ecs.CpuArchitecture.ARM64,
        operatingSystemFamily: ecs.OperatingSystemFamily.LINUX,
      },
    });

    apiTaskDef.addContainer('NipunaApi', {
      image: ecs.ContainerImage.fromEcrRepository(props.apiRepo, 'latest'),
      portMappings: [{ containerPort: 8000, protocol: ecs.Protocol.TCP }],
      logging: ecs.LogDrivers.awsLogs({
        streamPrefix: 'nipuna-api',
      }),
      environment: {
        ENV: 'production',
        AWS_SECRETS_MANAGER_SECRET_NAME: 'nipuna-secrets',
        REDIS_URL: `redis://${props.redisEndpoint}:6379/0`,
        CELERY_BROKER_URL: `redis://${props.redisEndpoint}:6379/0`,
        OPENSEARCH_ENDPOINT: props.openSearchEndpoint,
        DATABASE_URL: `postgresql+asyncpg://${props.databaseSecret.secretValueFromJson('username').unsafeUnwrap()}:${props.databaseSecret.secretValueFromJson('password').unsafeUnwrap()}@${props.databaseEndpoint}/nipunadb`,
      },
      healthCheck: {
        command: ['CMD-SHELL', 'python -c "import urllib.request; urllib.request.urlopen(\'http://localhost:8000/health\')"'],
        interval: cdk.Duration.seconds(30),
        timeout: cdk.Duration.seconds(5),
        startPeriod: cdk.Duration.seconds(20),
        retries: 2,
      },
    });

    const apiService = new ecs.FargateService(this, 'NipunaApiService', {
      cluster,
      taskDefinition: apiTaskDef,
      securityGroups: [ecsSg],
      desiredCount: 1,
    });
    this.apiServiceArn = apiService.serviceArn;

    listener.addTargets('ApiTarget', {
      port: 8000,
      protocol: elbv2.ApplicationProtocol.HTTP,
      targets: [apiService],
      healthCheck: {
        path: '/health',
        interval: cdk.Duration.seconds(30),
        timeout: cdk.Duration.seconds(5),
        healthyThresholdCount: 2,
        unhealthyThresholdCount: 3,
      },
    });

    if (isProd) {
      const scaling = apiService.autoScaleTaskCount({
        minCapacity: 1,
        maxCapacity: 10,
      });

      scaling.scaleOnCpuUtilization('CpuScaling', {
        targetUtilizationPercent: 70,
      });
    }

    const workerTaskDef = new ecs.FargateTaskDefinition(this, 'WorkerTaskDef', {
      cpu: 512,
      memoryLimitMiB: 1024,
      taskRole,
      executionRole,
      runtimePlatform: {
        cpuArchitecture: ecs.CpuArchitecture.ARM64,
        operatingSystemFamily: ecs.OperatingSystemFamily.LINUX,
      },
    });

    workerTaskDef.addContainer('NipunaWorker', {
      image: ecs.ContainerImage.fromEcrRepository(props.workerRepo, 'latest'),
      logging: ecs.LogDrivers.awsLogs({
        streamPrefix: 'nipuna-worker',
      }),
      environment: {
        ENV: 'production',
        AWS_SECRETS_MANAGER_SECRET_NAME: 'nipuna-secrets',
        REDIS_URL: `redis://${props.redisEndpoint}:6379/0`,
        CELERY_BROKER_URL: `redis://${props.redisEndpoint}:6379/0`,
        OPENSEARCH_ENDPOINT: props.openSearchEndpoint,
        DATABASE_URL: `postgresql+asyncpg://${props.databaseSecret.secretValueFromJson('username').unsafeUnwrap()}:${props.databaseSecret.secretValueFromJson('password').unsafeUnwrap()}@${props.databaseEndpoint}/nipunadb`,
      },
    });

    const workerService = new ecs.FargateService(this, 'NipunaWorkerService', {
      cluster,
      taskDefinition: workerTaskDef,
      securityGroups: [ecsSg],
      desiredCount: 1,
    });
    this.workerServiceArn = workerService.serviceArn;

    if (isProd) {
      new cloudwatch.CfnAlarm(this, 'Alb5xxAlarm', {
        alarmName: 'nipuna-alb-5xx-rate',
        alarmDescription: 'ALB 5xx rate exceeds threshold',
        metricName: 'HTTPCode_ELB_5XX_Count',
        namespace: 'AWS/ApplicationELB',
        statistic: 'Sum',
        period: 300,
        evaluationPeriods: 2,
        threshold: 10,
        comparisonOperator: 'GreaterThanThreshold',
        dimensions: [{ name: 'LoadBalancer', value: alb.loadBalancerFullName }],
      });

      new cloudwatch.CfnAlarm(this, 'EcsCpuAlarm', {
        alarmName: 'nipuna-ecs-cpu-high',
        alarmDescription: 'ECS API CPU utilization exceeds 80%',
        metricName: 'CPUUtilization',
        namespace: 'AWS/ECS',
        statistic: 'Average',
        period: 300,
        evaluationPeriods: 2,
        threshold: 80,
        comparisonOperator: 'GreaterThanThreshold',
        dimensions: [
          { name: 'ClusterName', value: cluster.clusterName },
          { name: 'ServiceName', value: apiService.serviceName },
        ],
      });
    }

    new cdk.CfnOutput(this, 'AlbDnsName', {
      value: alb.loadBalancerDnsName,
    });

    new cdk.CfnOutput(this, 'ClusterName', {
      value: cluster.clusterName,
    });
  }
}
