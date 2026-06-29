"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.EcsStack = void 0;
const cdk = __importStar(require("aws-cdk-lib"));
const ec2 = __importStar(require("aws-cdk-lib/aws-ec2"));
const ecs = __importStar(require("aws-cdk-lib/aws-ecs"));
const elbv2 = __importStar(require("aws-cdk-lib/aws-elasticloadbalancingv2"));
const iam = __importStar(require("aws-cdk-lib/aws-iam"));
const cloudwatch = __importStar(require("aws-cdk-lib/aws-cloudwatch"));
const acm = __importStar(require("aws-cdk-lib/aws-certificatemanager"));
class EcsStack extends cdk.Stack {
    clusterArn;
    apiServiceArn;
    workerServiceArn;
    constructor(scope, id, props) {
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
exports.EcsStack = EcsStack;
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoiZWNzLXN0YWNrLmpzIiwic291cmNlUm9vdCI6IiIsInNvdXJjZXMiOlsiZWNzLXN0YWNrLnRzIl0sIm5hbWVzIjpbXSwibWFwcGluZ3MiOiI7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7OztBQUFBLGlEQUFtQztBQUVuQyx5REFBMkM7QUFDM0MseURBQTJDO0FBQzNDLDhFQUFnRTtBQUNoRSx5REFBMkM7QUFFM0MsdUVBQXlEO0FBQ3pELHdFQUEwRDtBQWMxRCxNQUFhLFFBQVMsU0FBUSxHQUFHLENBQUMsS0FBSztJQUNyQixVQUFVLENBQVM7SUFDbkIsYUFBYSxDQUFTO0lBQ3RCLGdCQUFnQixDQUFTO0lBRXpDLFlBQVksS0FBZ0IsRUFBRSxFQUFVLEVBQUUsS0FBb0I7UUFDNUQsS0FBSyxDQUFDLEtBQUssRUFBRSxFQUFFLEVBQUUsS0FBSyxDQUFDLENBQUM7UUFFeEIsTUFBTSxNQUFNLEdBQUcsSUFBSSxDQUFDLElBQUksQ0FBQyxhQUFhLENBQUMsUUFBUSxDQUFDLENBQUM7UUFDakQsTUFBTSxjQUFjLEdBQUcsSUFBSSxDQUFDLElBQUksQ0FBQyxhQUFhLENBQUMsZ0JBQWdCLENBQUMsQ0FBQztRQUVqRSxNQUFNLE9BQU8sR0FBRyxJQUFJLEdBQUcsQ0FBQyxPQUFPLENBQUMsSUFBSSxFQUFFLGVBQWUsRUFBRTtZQUNyRCxHQUFHLEVBQUUsS0FBSyxDQUFDLEdBQUc7WUFDZCxpQkFBaUIsRUFBRSxJQUFJO1NBQ3hCLENBQUMsQ0FBQztRQUNILElBQUksQ0FBQyxVQUFVLEdBQUcsT0FBTyxDQUFDLFVBQVUsQ0FBQztRQUVyQyxNQUFNLEtBQUssR0FBRyxJQUFJLEdBQUcsQ0FBQyxhQUFhLENBQUMsSUFBSSxFQUFFLE9BQU8sRUFBRTtZQUNqRCxHQUFHLEVBQUUsS0FBSyxDQUFDLEdBQUc7WUFDZCxnQkFBZ0IsRUFBRSxJQUFJO1NBQ3ZCLENBQUMsQ0FBQztRQUNILEtBQUssQ0FBQyxjQUFjLENBQUMsR0FBRyxDQUFDLElBQUksQ0FBQyxPQUFP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QWEsRUFBRTtnQkFDM0MsU0FBUyxFQUFFLHFCQUFxQjtnQkFDaEMsZ0JBQWdCLEVBQUUscUNBQXFDO2dCQUN2RCxVQUFVLEVBQUUsZ0JBQWdCO2dCQUM1QixTQUFTLEVBQUUsU0FBUztnQkFDcEIsU0FBUyxFQUFFLFNBQVM7Z0JBQ3BCLE1BQU0sRUFBRSxHQUFHO2dCQUNYLGlCQUFpQixFQUFFLENBQUM7Z0JBQ3BCLFNBQVMsRUFBRSxFQUFFO2dCQUNiLGtCQUFrQixFQUFFLHNCQUFzQjtnQkFDMUMsVUFBVSxFQUFFO29CQUNWLEVBQUUsSUFBSSxFQUFFLGFBQWEsRUFBRSxLQUFLLEVBQUUsT0FBTyxDQUFDLFdBQVcsRUFBRTtvQkFDbkQsRUFBRSxJQUFJLEVBQUUsYUFBYSxFQUFFLEtBQUssRUFBRSxVQUFVLENBQUMsV0FBVyxFQUFFO2lCQUN2RDthQUNGLENBQUMsQ0FBQztRQUNMLENBQUM7UUFFRCxJQUFJLEdBQUcsQ0FBQyxTQUFTLENBQUMsSUFBSSxFQUFFLFlBQVksRUFBRTtZQUNwQyxLQUFLLEVBQUUsR0FBRyxDQUFDLG1CQUFtQjtTQUMvQixDQUFDLENBQUM7UUFFSCxJQUFJLEdBQUcsQ0FBQyxTQUFTLENBQUMsSUFBSSxFQUFFLGFBQWEsRUFBRTtZQUNyQyxLQUFLLEVBQUUsT0FBTyxDQUFDLFdBQVc7U0FDM0IsQ0FBQyxDQUFDO0lBQ0wsQ0FBQztDQUNGO0FBL05ELDRCQStOQyIsInNvdXJjZXNDb250ZW50IjpbImltcG9ydCAqIGFzIGNkayBmcm9tICdhd3MtY2RrLWxpYic7XG5pbXBvcnQgeyBDb25zdHJ1Y3QgfSBmcm9tICdjb25zdHJ1Y3RzJztcbmltcG9ydCAqIGFzIGVjMiBmcm9tICdhd3MtY2RrLWxpYi9hd3MtZWMyJztcbmltcG9ydCAqIGFzIGVjcyBmcm9tICdhd3MtY2RrLWxpYi9hd3MtZWNzJztcbmltcG9ydCAqIGFzIGVsYnYyIGZyb20gJ2F3cy1jZGstbGliL2F3cy1lbGFzdGljbG9hZGJhbGFuY2luZ3YyJztcbmltcG9ydCAqIGFzIGlhbSBmcm9tICdhd3MtY2RrLWxpYi9hd3MtaWFtJztcbmltcG9ydCAqIGFzIGVjciBmcm9tICdhd3MtY2RrLWxpYi9hd3MtZWNyJztcbmltcG9ydCAqIGFzIGNsb3Vkd2F0Y2ggZnJvbSAnYXdzLWNkay1saWIvYXdzLWNsb3Vkd2F0Y2gnO1xuaW1wb3J0ICogYXMgYWNtIGZyb20gJ2F3cy1jZGstbGliL2F3cy1jZXJ0aWZpY2F0ZW1hbmFnZXInO1xuXG5pbnRlcmZhY2UgRWNzU3RhY2tQcm9wcyBleHRlbmRzIGNkay5TdGFja1Byb3BzIHtcbiAgdnBjOiBlYzIuVnBjO1xuICBhcGlSZXBvOiBlY3IuUmVwb3NpdG9yeTtcbiAgd29ya2VyUmVwbzogZWNyLlJlcG9zaXRvcnk7XG4gIGRhdGFiYXNlU2VjcmV0OiBjZGsuYXdzX3NlY3JldHNtYW5hZ2VyLklTZWNyZXQ7XG4gIGRhdGFiYXNlRW5kcG9pbnQ6IHN0cmluZztcbiAgcmVkaXNFbmRwb2ludDogc3RyaW5nO1xuICBvcGVuU2VhcmNoRW5kcG9pbnQ6IHN0cmluZztcbiAgcmRzU2c6IGVjMi5JU2VjdXJpdHlHcm91cDtcbiAgcmVkaXNTZzogZWMyLklTZWN1cml0eUdyb3VwO1xufVxuXG5leHBvcnQgY2xhc3MgRWNzU3RhY2sgZXh0ZW5kcyBjZGsuU3RhY2sge1xuICBwdWJsaWMgcmVhZG9ubHkgY2x1c3RlckFybjogc3RyaW5nO1xuICBwdWJsaWMgcmVhZG9ubHkgYXBpU2VydmljZUFybjogc3RyaW5nO1xuICBwdWJsaWMgcmVhZG9ubHkgd29ya2VyU2VydmljZUFybjogc3RyaW5nO1xuXG4gIGNvbnN0cnVjdG9yKHNjb3BlOiBDb25zdHJ1Y3QsIGlkOiBzdHJpbmcsIHByb3BzOiBFY3NTdGFja1Byb3BzKSB7XG4gICAgc3VwZXIoc2NvcGUsIGlkLCBwcm9wcyk7XG5cbiAgICBjb25zdCBpc1Byb2QgPSB0aGlzLm5vZGUudHJ5R2V0Q29udGV4dCgnaXNQcm9kJyk7XG4gICAgY29uc3QgY2VydGlmaWNhdGVBcm4gPSB0aGlzLm5vZGUudHJ5R2V0Q29udGV4dCgnY2VydGlmaWNhdGVBcm4nKTtcblxuICAgIGNvbnN0IGNsdXN0ZXIgPSBuZXcgZWNzLkNsdXN0ZXIodGhpcywgJ05pcHVuYUNsdXN0ZXInLCB7XG4gICAgICB2cGM6IHByb3BzLnZwYyxcbiAgICAgIGNvbnRhaW5lckluc2lnaHRzOiB0cnVlLFxuICAgIH0pO1xuICAgIHRoaXMuY2x1c3RlckFybiA9IGNsdXN0ZXIuY2x1c3RlckFybjtcblxuICAgIGNvbnN0IGFsYlNnID0gbmV3IGVjMi5TZWN1cml0eUdyb3VwKHRoaXMsICdBbGJTZycsIHtcbiAgICAgIHZwYzogcHJvcHMudnBjLFxuICAgICAgYWxsb3dBbGxPdXRib3VuZDogdHJ1ZSxcbiAgICB9KTtcbiAgICBhbGJTZy5hZGRJbmdyZXNzUnVsZShlYzIuUGVlci5hbnlJcHY0KCksIGVjMi5Qb3J0LnRjcChjZXJ0aWZpY2F0ZUFybiA/IDQ0MyA6IDgwKSk7XG5cbiAgICBjb25zdCBlY3NTZyA9IG5ldyBlYzIuU2VjdXJpdHlHcm91cCh0aGlzLCAnRWNzU2cnLCB7XG4gICAgICB2cGM6IHByb3BzLnZwYyxcbiAgICAgIGFsbG93QWxsT3V0Ym91bmQ6IHRydWUsXG4gICAgfSk7XG4gICAgZWNzU2cuYWRkSW5ncmVzc1J1bGUoYWxiU2csIGVjMi5Qb3J0LnRjcCg4MDAwKSk7XG5cbiAgICBuZXcgZWMyLkNmblNlY3VyaXR5R3JvdXBJbmdyZXNzKHRoaXMsICdSZHNFY3NJbmdyZXNzJywge1xuICAgICAgZ3JvdXBJZDogcHJvcHMucmRzU2cuc2VjdXJpdHlHcm91cElkLFxuICAgICAgc291cmNlU2VjdXJpdHlHcm91cElkOiBlY3NTZy5zZWN1cml0eUdyb3VwSWQsXG4gICAgICBpcFByb3RvY29sOiAndGNwJyxcbiAgICAgIGZyb21Qb3J0OiA1NDMyLFxuICAgICAgdG9Qb3J0OiA1NDMyLFxuICAgIH0pO1xuXG4gICAgbmV3IGVjMi5DZm5TZWN1cml0eUdyb3VwSW5ncmVzcyh0aGlzLCAnUmVkaXNFY3NJbmdyZXNzJywge1xuICAgICAgZ3JvdXBJZDogcHJvcHMucmVkaXNTZy5zZWN1cml0eUdyb3VwSWQsXG4gICAgICBzb3VyY2VTZWN1cml0eUdyb3VwSWQ6IGVjc1NnLnNlY3VyaXR5R3JvdXBJZCxcbiAgICAgIGlwUHJvdG9jb2w6ICd0Y3AnLFxuICAgICAgZnJvbVBvcnQ6IDYzNzksXG4gICAgICB0b1BvcnQ6IDYzNzksXG4gICAgfSk7XG5cbiAgICBjb25zdCBhbGIgPSBuZXcgZWxidjIuQXBwbGljYXRpb25Mb2FkQmFsYW5jZXIodGhpcywgJ05pcHVuYUFsYicsIHtcbiAgICAgIHZwYzogcHJvcHMudnBjLFxuICAgICAgaW50ZXJuZXRGYWNpbmc6IHRydWUsXG4gICAgICBzZWN1cml0eUdyb3VwOiBhbGJTZyxcbiAgICB9KTtcblxuICAgIGNvbnN0IGxpc3RlbmVyID0gYWxiLmFkZExpc3RlbmVyKGNlcnRpZmljYXRlQXJuID8gJ0h0dHBzTGlzdGVuZXInIDogJ0h0dHBMaXN0ZW5lcicsIHtcbiAgICAgIHBvcnQ6IGNlcnRpZmljYXRlQXJuID8gNDQzIDogODAsXG4gICAgICBwcm90b2NvbDogY2VydGlmaWNhdGVBcm4gPyBlbGJ2Mi5BcHBsaWNhdGlvblByb3RvY29sLkhUVFBTIDogZWxidjIuQXBwbGljYXRpb25Qcm90b2NvbC5IVFRQLFxuICAgICAgY2VydGlmaWNhdGVzOiBjZXJ0aWZpY2F0ZUFyblxuICAgICAgICA/IFthY20uQ2VydGlmaWNhdGUuZnJvbUNlcnRpZmljYXRlQXJuKHRoaXMsICdBbGJDZXJ0aWZpY2F0ZScsIGNlcnRpZmljYXRlQXJuKV1cbiAgICAgICAgOiB1bmRlZmluZWQsXG4gICAgfSk7XG5cbiAgICBjb25zdCB0YXNrUm9sZSA9IG5ldyBpYW0uUm9sZSh0aGlzLCAnRWNzVGFza1JvbGUnLCB7XG4gICAgICByb2xlTmFtZTogJ25pcHVuYS1lY3MtdGFzay1yb2xlJyxcbiAgICAgIGFzc3VtZWRCeTogbmV3IGlhbS5TZXJ2aWNlUHJpbmNpcGFsKCdlY3MtdGFza3MuYW1hem9uYXdzLmNvbScpLFxuICAgICAgbWFuYWdlZFBvbGljaWVzOiBbXG4gICAgICAgIGlhbS5NYW5hZ2VkUG9saWN5LmZyb21Bd3NNYW5hZ2VkUG9saWN5TmFtZSgnc2VydmljZS1yb2xlL0FtYXpvbkVDU1Rhc2tFeGVjdXRpb25Sb2xlUG9saWN5JyksXG4gICAgICBdLFxuICAgIH0pO1xuXG4gICAgdGFza1JvbGUuYWRkVG9Qb2xpY3kobmV3IGlhbS5Qb2xpY3lTdGF0ZW1lbnQoe1xuICAgICAgYWN0aW9uczogWydzZWNyZXRzbWFuYWdlcjpHZXRTZWNyZXRWYWx1ZSddLFxuICAgICAgcmVzb3VyY2VzOiBbJyonXSxcbiAgICB9KSk7XG5cbiAgICB0YXNrUm9sZS5hZGRUb1BvbGljeShuZXcgaWFtLlBvbGljeVN0YXRlbWVudCh7XG4gICAgICBhY3Rpb25zOiBbJ29wZW5zZWFyY2hzZXJ2ZXJsZXNzOionXSxcbiAgICAgIHJlc291cmNlczogWycqJ10sXG4gICAgfSkpO1xuXG4gICAgY29uc3QgZXhlY3V0aW9uUm9sZSA9IG5ldyBpYW0uUm9sZSh0aGlzLCAnRWNzRXhlY3V0aW9uUm9sZScsIHtcbiAgICAgIGFzc3VtZWRCeTogbmV3IGlhbS5TZXJ2aWNlUHJpbmNpcGFsKCdlY3MtdGFza3MuYW1hem9uYXdzLmNvbScpLFxuICAgICAgbWFuYWdlZFBvbGljaWVzOiBbXG4gICAgICAgIGlhbS5NYW5hZ2VkUG9saWN5LmZyb21Bd3NNYW5hZ2VkUG9saWN5TmFtZSgnc2VydmljZS1yb2xlL0FtYXpvbkVDU1Rhc2tFeGVjdXRpb25Sb2xlUG9saWN5JyksXG4gICAgICBdLFxuICAgIH0pO1xuXG4gICAgY29uc3QgYXBpVGFza0RlZiA9IG5ldyBlY3MuRmFyZ2F0ZVRhc2tEZWZpbml0aW9uKHRoaXMsICdBcGlUYXNrRGVmJywge1xuICAgICAgY3B1OiA1MTIsXG4gICAgICBtZW1vcnlMaW1pdE1pQjogMTAyNCxcbiAgICAgIHRhc2tSb2xlLFxuICAgICAgZXhlY3V0aW9uUm9sZSxcbiAgICAgIHJ1bnRpbWVQbGF0Zm9ybToge1xuICAgICAgICBjcHVBcmNoaXRlY3R1cmU6IGVjcy5DcHVBcmNoaXRlY3R1cmUuQVJNNjQsXG4gICAgICAgIG9wZXJhdGluZ1N5c3RlbUZhbWlseTogZWNzLk9wZXJhdGluZ1N5c3RlbUZhbWlseS5MSU5VWCxcbiAgICAgIH0sXG4gICAgfSk7XG5cbiAgICBhcGlUYXNrRGVmLmFkZENvbnRhaW5lcignTmlwdW5hQXBpJywge1xuICAgICAgaW1hZ2U6IGVjcy5Db250YWluZXJJbWFnZS5mcm9tRWNyUmVwb3NpdG9yeShwcm9wcy5hcGlSZXBvLCAnbGF0ZXN0JyksXG4gICAgICBwb3J0TWFwcGluZ3M6IFt7IGNvbnRhaW5lclBvcnQ6IDgwMDAsIHByb3RvY29sOiBlY3MuUHJvdG9jb2wuVENQIH1dLFxuICAgICAgbG9nZ2luZzogZWNzLkxvZ0RyaXZlcnMuYXdzTG9ncyh7XG4gICAgICAgIHN0cmVhbVByZWZpeDogJ25pcHVuYS1hcGknLFxuICAgICAgfSksXG4gICAgICBlbnZpcm9ubWVudDoge1xuICAgICAgICBFTlY6ICdwcm9kdWN0aW9uJyxcbiAgICAgICAgQVdTX1NFQ1JFVFNfTUFOQUdFUl9TRUNSRVRfTkFNRTogJ25pcHVuYS1zZWNyZXRzJyxcbiAgICAgICAgUkVESVNfVVJMOiBgcmVkaXM6Ly8ke3Byb3BzLnJlZGlzRW5kcG9pbnR9OjYzNzkvMGAsXG4gICAgICAgIENFTEVSWV9CUk9LRVJfVVJMOiBgcmVkaXM6Ly8ke3Byb3BzLnJlZGlzRW5kcG9pbnR9OjYzNzkvMGAsXG4gICAgICAgIE9QRU5TRUFSQ0hfRU5EUE9JTlQ6IHByb3BzLm9wZW5TZWFyY2hFbmRwb2ludCxcbiAgICAgICAgREFUQUJBU0VfVVJMOiBgcG9zdGdyZXNxbCthc3luY3BnOi8vJHtwcm9wcy5kYXRhYmFzZVNlY3JldC5zZWNyZXRWYWx1ZUZyb21Kc29uKCd1c2VybmFtZScpLnVuc2FmZVVud3JhcCgpfToke3Byb3BzLmRhdGFiYXNlU2VjcmV0LnNlY3JldFZhbHVlRnJvbUpzb24oJ3Bhc3N3b3JkJykudW5zYWZlVW53cmFwKCl9QCR7cHJvcHMuZGF0YWJhc2VFbmRwb2ludH0vbmlwdW5hZGJgLFxuICAgICAgfSxcbiAgICAgIGhlYWx0aENoZWNrOiB7XG4gICAgICAgIGNvbW1hbmQ6IFsnQ01ELVNIRUxMJywgJ3B5dGhvbiAtYyBcImltcG9ydCB1cmxsaWIucmVxdWVzdDsgdXJsbGliLnJlcXVlc3QudXJsb3BlbihcXCdodHRwOi8vbG9jYWxob3N0OjgwMDAvaGVhbHRoXFwnKVwiJ10sXG4gICAgICAgIGludGVydmFsOiBjZGsuRHVyYXRpb24uc2Vjb25kcygzMCksXG4gICAgICAgIHRpbWVvdXQ6IGNkay5EdXJhdGlvbi5zZWNvbmRzKDUpLFxuICAgICAgICBzdGFydFBlcmlvZDogY2RrLkR1cmF0aW9uLnNlY29uZHMoMjApLFxuICAgICAgICByZXRyaWVzOiAyLFxuICAgICAgfSxcbiAgICB9KTtcblxuICAgIGNvbnN0IGFwaVNlcnZpY2UgPSBuZXcgZWNzLkZhcmdhdGVTZXJ2aWNlKHRoaXMsICdOaXB1bmFBcGlTZXJ2aWNlJywge1xuICAgICAgY2x1c3RlcixcbiAgICAgIHRhc2tEZWZpbml0aW9uOiBhcGlUYXNrRGVmLFxuICAgICAgc2VjdXJpdHlHcm91cHM6IFtlY3NTZ10sXG4gICAgICBkZXNpcmVkQ291bnQ6IDEsXG4gICAgfSk7XG4gICAgdGhpcy5hcGlTZXJ2aWNlQXJuID0gYXBpU2VydmljZS5zZXJ2aWNlQXJuO1xuXG4gICAgbGlzdGVuZXIuYWRkVGFyZ2V0cygnQXBpVGFyZ2V0Jywge1xuICAgICAgcG9ydDogODAwMCxcbiAgICAgIHByb3RvY29sOiBlbGJ2Mi5BcHBsaWNhdGlvblByb3RvY29sLkhUVFAsXG4gICAgICB0YXJnZXRzOiBbYXBpU2VydmljZV0sXG4gICAgICBoZWFsdGhDaGVjazoge1xuICAgICAgICBwYXRoOiAnL2hlYWx0aCcsXG4gICAgICAgIGludGVydmFsOiBjZGsuRHVyYXRpb24uc2Vjb25kcygzMCksXG4gICAgICAgIHRpbWVvdXQ6IGNkay5EdXJhdGlvbi5zZWNvbmRzKDUpLFxuICAgICAgICBoZWFsdGh5VGhyZXNob2xkQ291bnQ6IDIsXG4gICAgICAgIHVuaGVhbHRoeVRocmVzaG9sZENvdW50OiAzLFxuICAgICAgfSxcbiAgICB9KTtcblxuICAgIGlmIChpc1Byb2QpIHtcbiAgICAgIGNvbnN0IHNjYWxpbmcgPSBhcGlTZXJ2aWNlLmF1dG9TY2FsZVRhc2tDb3VudCh7XG4gICAgICAgIG1pbkNhcGFjaXR5OiAxLFxuICAgICAgICBtYXhDYXBhY2l0eTogMTAsXG4gICAgICB9KTtcblxuICAgICAgc2NhbGluZy5zY2FsZU9uQ3B1VXRpbGl6YXRpb24oJ0NwdVNjYWxpbmcnLCB7XG4gICAgICAgIHRhcmdldFV0aWxpemF0aW9uUGVyY2VudDogNzAsXG4gICAgICB9KTtcbiAgICB9XG5cbiAgICBjb25zdCB3b3JrZXJUYXNrRGVmID0gbmV3IGVjcy5GYXJnYXRlVGFza0RlZmluaXRpb24odGhpcywgJ1dvcmtlclRhc2tEZWYnLCB7XG4gICAgICBjcHU6IDUxMixcbiAgICAgIG1lbW9yeUxpbWl0TWlCOiAxMDI0LFxuICAgICAgdGFza1JvbGUsXG4gICAgICBleGVjdXRpb25Sb2xlLFxuICAgICAgcnVudGltZVBsYXRmb3JtOiB7XG4gICAgICAgIGNwdUFyY2hpdGVjdHVyZTogZWNzLkNwdUFyY2hpdGVjdHVyZS5BUk02NCxcbiAgICAgICAgb3BlcmF0aW5nU3lzdGVtRmFtaWx5OiBlY3MuT3BlcmF0aW5nU3lzdGVtRmFtaWx5LkxJTlVYLFxuICAgICAgfSxcbiAgICB9KTtcblxuICAgIHdvcmtlclRhc2tEZWYuYWRkQ29udGFpbmVyKCdOaXB1bmFXb3JrZXInLCB7XG4gICAgICBpbWFnZTogZWNzLkNvbnRhaW5lckltYWdlLmZyb21FY3JSZXBvc2l0b3J5KHByb3BzLndvcmtlclJlcG8sICdsYXRlc3QnKSxcbiAgICAgIGxvZ2dpbmc6IGVjcy5Mb2dEcml2ZXJzLmF3c0xvZ3Moe1xuICAgICAgICBzdHJlYW1QcmVmaXg6ICduaXB1bmEtd29ya2VyJyxcbiAgICAgIH0pLFxuICAgICAgZW52aXJvbm1lbnQ6IHtcbiAgICAgICAgRU5WOiAncHJvZHVjdGlvbicsXG4gICAgICAgIEFXU19TRUNSRVRTX01BTkFHRVJfU0VDUkVUX05BTUU6ICduaXB1bmEtc2VjcmV0cycsXG4gICAgICAgIFJFRElTX1VSTDogYHJlZGlzOi8vJHtwcm9wcy5yZWRpc0VuZHBvaW50fTo2Mzc5LzBgLFxuICAgICAgICBDRUxFUllfQlJPS0VSX1VSTDogYHJlZGlzOi8vJHtwcm9wcy5yZWRpc0VuZHBvaW50fTo2Mzc5LzBgLFxuICAgICAgICBPUEVOU0VBUkNIX0VORFBPSU5UOiBwcm9wcy5vcGVuU2VhcmNoRW5kcG9pbnQsXG4gICAgICAgIERBVEFCQVNFX1VSTDogYHBvc3RncmVzcWwrYXN5bmNwZzovLyR7cHJvcHMuZGF0YWJhc2VTZWNyZXQuc2VjcmV0VmFsdWVGcm9tSnNvbigndXNlcm5hbWUnKS51bnNhZmVVbndyYXAoKX06JHtwcm9wcy5kYXRhYmFzZVNlY3JldC5zZWNyZXRWYWx1ZUZyb21Kc29uKCdwYXNzd29yZCcpLnVuc2FmZVVud3JhcCgpfUAke3Byb3BzLmRhdGFiYXNlRW5kcG9pbnR9L25pcHVuYWRiYCxcbiAgICAgIH0sXG4gICAgfSk7XG5cbiAgICBjb25zdCB3b3JrZXJTZXJ2aWNlID0gbmV3IGVjcy5GYXJnYXRlU2VydmljZSh0aGlzLCAnTmlwdW5hV29ya2VyU2VydmljZScsIHtcbiAgICAgIGNsdXN0ZXIsXG4gICAgICB0YXNrRGVmaW5pdGlvbjogd29ya2VyVGFza0RlZixcbiAgICAgIHNlY3VyaXR5R3JvdXBzOiBbZWNzU2ddLFxuICAgICAgZGVzaXJlZENvdW50OiAxLFxuICAgIH0pO1xuICAgIHRoaXMud29ya2VyU2VydmljZUFybiA9IHdvcmtlclNlcnZpY2Uuc2VydmljZUFybjtcblxuICAgIGlmIChpc1Byb2QpIHtcbiAgICAgIG5ldyBjbG91ZHdhdGNoLkNmbkFsYXJtKHRoaXMsICdBbGI1eHhBbGFybScsIHtcbiAgICAgICAgYWxhcm1OYW1lOiAnbmlwdW5hLWFsYi01eHgtcmF0ZScsXG4gICAgICAgIGFsYXJtRGVzY3JpcHRpb246ICdBTEIgNXh4IHJhdGUgZXhjZWVkcyB0aHJlc2hvbGQnLFxuICAgICAgICBtZXRyaWNOYW1lOiAnSFRUUENvZGVfRUxCXzVYWF9Db3VudCcsXG4gICAgICAgIG5hbWVzcGFjZTogJ0FXUy9BcHBsaWNhdGlvbkVMQicsXG4gICAgICAgIHN0YXRpc3RpYzogJ1N1bScsXG4gICAgICAgIHBlcmlvZDogMzAwLFxuICAgICAgICBldmFsdWF0aW9uUGVyaW9kczogMixcbiAgICAgICAgdGhyZXNob2xkOiAxMCxcbiAgICAgICAgY29tcGFyaXNvbk9wZXJhdG9yOiAnR3JlYXRlclRoYW5UaHJlc2hvbGQnLFxuICAgICAgICBkaW1lbnNpb25zOiBbeyBuYW1lOiAnTG9hZEJhbGFuY2VyJywgdmFsdWU6IGFsYi5sb2FkQmFsYW5jZXJGdWxsTmFtZSB9XSxcbiAgICAgIH0pO1xuXG4gICAgICBuZXcgY2xvdWR3YXRjaC5DZm5BbGFybSh0aGlzLCAnRWNzQ3B1QWxhcm0nLCB7XG4gICAgICAgIGFsYXJtTmFtZTogJ25pcHVuYS1lY3MtY3B1LWhpZ2gnLFxuICAgICAgICBhbGFybURlc2NyaXB0aW9uOiAnRUNTIEFQSSBDUFUgdXRpbGl6YXRpb24gZXhjZWVkcyA4MCUnLFxuICAgICAgICBtZXRyaWNOYW1lOiAnQ1BVVXRpbGl6YXRpb24nLFxuICAgICAgICBuYW1lc3BhY2U6ICdBV1MvRUNTJyxcbiAgICAgICAgc3RhdGlzdGljOiAnQXZlcmFnZScsXG4gICAgICAgIHBlcmlvZDogMzAwLFxuICAgICAgICBldmFsdWF0aW9uUGVyaW9kczogMixcbiAgICAgICAgdGhyZXNob2xkOiA4MCxcbiAgICAgICAgY29tcGFyaXNvbk9wZXJhdG9yOiAnR3JlYXRlclRoYW5UaHJlc2hvbGQnLFxuICAgICAgICBkaW1lbnNpb25zOiBbXG4gICAgICAgICAgeyBuYW1lOiAnQ2x1c3Rlck5hbWUnLCB2YWx1ZTogY2x1c3Rlci5jbHVzdGVyTmFtZSB9LFxuICAgICAgICAgIHsgbmFtZTogJ1NlcnZpY2VOYW1lJywgdmFsdWU6IGFwaVNlcnZpY2Uuc2VydmljZU5hbWUgfSxcbiAgICAgICAgXSxcbiAgICAgIH0pO1xuICAgIH1cblxuICAgIG5ldyBjZGsuQ2ZuT3V0cHV0KHRoaXMsICdBbGJEbnNOYW1lJywge1xuICAgICAgdmFsdWU6IGFsYi5sb2FkQmFsYW5jZXJEbnNOYW1lLFxuICAgIH0pO1xuXG4gICAgbmV3IGNkay5DZm5PdXRwdXQodGhpcywgJ0NsdXN0ZXJOYW1lJywge1xuICAgICAgdmFsdWU6IGNsdXN0ZXIuY2x1c3Rlck5hbWUsXG4gICAgfSk7XG4gIH1cbn1cbiJdfQ==