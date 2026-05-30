#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { VpcStack } from '../lib/vpc-stack';
import { RdsStack } from '../lib/rds-stack';
import { ElastiCacheStack } from '../lib/elasticache-stack';
import { OpenSearchStack } from '../lib/opensearch-stack';
import { EcrStack } from '../lib/ecr-stack';
import { EcsStack } from '../lib/ecs-stack';
import { PipelineRoleStack } from '../lib/pipeline-role-stack';

const app = new cdk.App();

const env = {
  account: process.env.CDK_DEFAULT_ACCOUNT,
  region: 'ap-south-1',
};

const vpcStack = new VpcStack(app, 'VpcStack', { env });

const rdsStack = new RdsStack(app, 'RdsStack', {
  env,
  vpc: vpcStack.vpc,
  rdsSg: vpcStack.rdsSg,
});

const elasticacheStack = new ElastiCacheStack(app, 'ElastiCacheStack', {
  env,
  vpc: vpcStack.vpc,
});

const openSearchStack = new OpenSearchStack(app, 'OpenSearchStack', {
  env,
  vpc: vpcStack.vpc,
});

const ecrStack = new EcrStack(app, 'EcrStack', { env });

const ecsStack = new EcsStack(app, 'EcsStack', {
  env,
  vpc: vpcStack.vpc,
  apiRepo: ecrStack.apiRepo,
  workerRepo: ecrStack.workerRepo,
  databaseSecret: rdsStack.databaseSecret,
  databaseEndpoint: rdsStack.databaseEndpoint,
  redisEndpoint: elasticacheStack.primaryEndpoint,
  openSearchEndpoint: openSearchStack.collectionEndpoint,
  rdsSg: vpcStack.rdsSg,
  redisSg: elasticacheStack.redisSg,
});

rdsStack.addDependency(vpcStack);
elasticacheStack.addDependency(vpcStack);
openSearchStack.addDependency(vpcStack);
ecsStack.addDependency(ecrStack);
ecsStack.addDependency(rdsStack);
ecsStack.addDependency(elasticacheStack);
ecsStack.addDependency(openSearchStack);

const pipelineRoleStack = new PipelineRoleStack(app, 'PipelineRoleStack', {
  env,
  apiRepo: ecrStack.apiRepo,
  workerRepo: ecrStack.workerRepo,
  ecsClusterArn: ecsStack.clusterArn,
  apiServiceArn: ecsStack.apiServiceArn,
  workerServiceArn: ecsStack.workerServiceArn,
});
pipelineRoleStack.addDependency(ecrStack);
pipelineRoleStack.addDependency(ecsStack);
