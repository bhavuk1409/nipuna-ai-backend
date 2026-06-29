import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecr from 'aws-cdk-lib/aws-ecr';
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
export declare class EcsStack extends cdk.Stack {
    readonly clusterArn: string;
    readonly apiServiceArn: string;
    readonly workerServiceArn: string;
    constructor(scope: Construct, id: string, props: EcsStackProps);
}
export {};
