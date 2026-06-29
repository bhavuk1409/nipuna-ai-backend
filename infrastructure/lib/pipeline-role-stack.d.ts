import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ecr from 'aws-cdk-lib/aws-ecr';
interface PipelineRoleStackProps extends cdk.StackProps {
    apiRepo: ecr.Repository;
    workerRepo: ecr.Repository;
    ecsClusterArn: string;
    apiServiceArn: string;
    workerServiceArn: string;
}
export declare class PipelineRoleStack extends cdk.Stack {
    readonly roleArn: string;
    constructor(scope: Construct, id: string, props: PipelineRoleStackProps);
}
export {};
