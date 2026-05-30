import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';

export class VpcStack extends cdk.Stack {
  public readonly vpc: ec2.Vpc;
  public readonly ecsSg: ec2.SecurityGroup;
  public readonly rdsSg: ec2.SecurityGroup;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const isProd = this.node.tryGetContext('isProd');

    this.vpc = new ec2.Vpc(this, 'NipunaVpc', {
      ipAddresses: ec2.IpAddresses.cidr('10.0.0.0/16'),
      maxAzs: 2,
      natGateways: isProd ? 2 : 1,

      subnetConfiguration: [
        {
          name: 'public',
          subnetType: ec2.SubnetType.PUBLIC,
          cidrMask: 24,
        },
        {
          name: 'private',
          subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS,
          cidrMask: 24,
        },
        {
          name: 'isolated',
          subnetType: ec2.SubnetType.PRIVATE_ISOLATED,
          cidrMask: 24,
        },
      ],
    });

    const albSg = new ec2.SecurityGroup(this, 'AlbSecurityGroup', {
      vpc: this.vpc,
      allowAllOutbound: true,
    });

    albSg.addIngressRule(
      ec2.Peer.anyIpv4(),
      ec2.Port.tcp(443)
    );

    this.ecsSg = new ec2.SecurityGroup(this, 'EcsSecurityGroup', {
      vpc: this.vpc,
      allowAllOutbound: true,
    });

    this.ecsSg.addIngressRule(
      albSg,
      ec2.Port.tcp(8000)
    );

    this.rdsSg = new ec2.SecurityGroup(this, 'RdsSecurityGroup', {
      vpc: this.vpc,
      allowAllOutbound: true,
    });

    this.rdsSg.addIngressRule(
      this.ecsSg,
      ec2.Port.tcp(5432)
    );

    new cdk.CfnOutput(this, 'VpcId', {
      value: this.vpc.vpcId,
    });
  }
}