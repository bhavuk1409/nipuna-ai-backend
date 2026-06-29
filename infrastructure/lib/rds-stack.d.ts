import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
interface RdsStackProps extends cdk.StackProps {
    vpc: ec2.Vpc;
    rdsSg: ec2.SecurityGroup;
}
export declare class RdsStack extends cdk.Stack {
    readonly databaseSecret: cdk.aws_secretsmanager.ISecret;
    readonly databaseEndpoint: string;
    constructor(scope: Construct, id: string, props: RdsStackProps);
}
export {};
