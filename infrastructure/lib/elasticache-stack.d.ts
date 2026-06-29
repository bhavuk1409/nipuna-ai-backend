import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
interface ElastiCacheStackProps extends cdk.StackProps {
    vpc: ec2.Vpc;
}
export declare class ElastiCacheStack extends cdk.Stack {
    readonly primaryEndpoint: string;
    readonly redisSg: ec2.SecurityGroup;
    constructor(scope: Construct, id: string, props: ElastiCacheStackProps);
}
export {};
