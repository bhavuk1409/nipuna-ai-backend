import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
export declare class VpcStack extends cdk.Stack {
    readonly vpc: ec2.Vpc;
    readonly ecsSg: ec2.SecurityGroup;
    readonly rdsSg: ec2.SecurityGroup;
    constructor(scope: Construct, id: string, props?: cdk.StackProps);
}
