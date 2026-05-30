import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as elasticache from 'aws-cdk-lib/aws-elasticache';

interface ElastiCacheStackProps extends cdk.StackProps {
  vpc: ec2.Vpc;
}

export class ElastiCacheStack extends cdk.Stack {
  public readonly primaryEndpoint: string;
  public readonly redisSg: ec2.SecurityGroup;

  constructor(scope: Construct, id: string, props: ElastiCacheStackProps) {
    super(scope, id, props);

    const isProd = this.node.tryGetContext('isProd');

    const sg = new ec2.SecurityGroup(this, 'RedisSecurityGroup', {
      vpc: props.vpc,
      allowAllOutbound: true,
    });

    this.redisSg = sg;

    const subnetGroup = new elasticache.CfnSubnetGroup(this, 'RedisSubnetGroup', {
      description: 'Subnet group for ElastiCache Redis',
      subnetIds: props.vpc.isolatedSubnets.map(s => s.subnetId),
    });

    const cluster = new elasticache.CfnCacheCluster(this, 'NipunaRedis', {
      cacheNodeType: isProd ? 'cache.r6g.large' : 'cache.t3.micro',
      engine: 'redis',
      engineVersion: '7.0',
      numCacheNodes: 1,
      vpcSecurityGroupIds: [sg.securityGroupId],
      cacheSubnetGroupName: subnetGroup.ref,
      autoMinorVersionUpgrade: true,
    });

    cluster.addDependency(subnetGroup);

    this.primaryEndpoint = cluster.attrRedisEndpointAddress;

    new cdk.CfnOutput(this, 'RedisEndpoint', {
      value: this.primaryEndpoint,
    });
  }
}
