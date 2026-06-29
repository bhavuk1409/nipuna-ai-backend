import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ecr from 'aws-cdk-lib/aws-ecr';
export declare class EcrStack extends cdk.Stack {
    readonly apiRepo: ecr.Repository;
    readonly workerRepo: ecr.Repository;
    constructor(scope: Construct, id: string, props?: cdk.StackProps);
}
