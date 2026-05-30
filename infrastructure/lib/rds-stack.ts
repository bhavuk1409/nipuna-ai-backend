import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as rds from 'aws-cdk-lib/aws-rds';
import * as ec2 from 'aws-cdk-lib/aws-ec2';

interface RdsStackProps extends cdk.StackProps {
  vpc: ec2.Vpc;
  rdsSg: ec2.SecurityGroup;
}

export class RdsStack extends cdk.Stack {
  public readonly databaseSecret: cdk.aws_secretsmanager.ISecret;
  public readonly databaseEndpoint: string;

  constructor(scope: Construct, id: string, props: RdsStackProps) {
    super(scope, id, props);

    const isProd = this.node.tryGetContext('isProd');

    const db = new rds.DatabaseInstance(this, 'NipunaPostgres', {
      engine: rds.DatabaseInstanceEngine.postgres({
        version: rds.PostgresEngineVersion.VER_15,
      }),

      instanceType: isProd
        ? ec2.InstanceType.of(
            ec2.InstanceClass.R6G,
            ec2.InstanceSize.LARGE
          )
        : ec2.InstanceType.of(
            ec2.InstanceClass.T3,
            ec2.InstanceSize.MEDIUM
          ),

      vpc: props.vpc,

      vpcSubnets: {
        subnetType: ec2.SubnetType.PRIVATE_ISOLATED,
      },

      securityGroups: [props.rdsSg],

      allocatedStorage: 20,
      maxAllocatedStorage: 100,

      multiAz: isProd,

      deletionProtection: isProd,

      databaseName: 'nipunadb',

      credentials: rds.Credentials.fromGeneratedSecret('postgres'),

      backupRetention: cdk.Duration.days(7),

      removalPolicy: isProd
        ? cdk.RemovalPolicy.RETAIN
        : cdk.RemovalPolicy.DESTROY,
    });

    this.databaseSecret = db.secret!;
    this.databaseEndpoint = db.dbInstanceEndpointAddress;

    new cdk.CfnOutput(this, 'DatabaseEndpoint', {
      value: db.dbInstanceEndpointAddress,
    });

    new cdk.CfnOutput(this, 'DatabaseSecretArn', {
      value: db.secret!.secretArn,
    });
  }
}