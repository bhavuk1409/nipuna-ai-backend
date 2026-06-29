import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
interface OpenSearchStackProps extends cdk.StackProps {
    vpc: ec2.Vpc;
}
export declare class OpenSearchStack extends cdk.Stack {
    readonly collectionEndpoint: string;
    constructor(scope: Construct, id: string, props: OpenSearchStackProps);
}
export {};
