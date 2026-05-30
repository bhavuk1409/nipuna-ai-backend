import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ecr from 'aws-cdk-lib/aws-ecr';

export class EcrStack extends cdk.Stack {
  public readonly apiRepo: ecr.Repository;
  public readonly workerRepo: ecr.Repository;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    this.apiRepo = new ecr.Repository(this, 'NipunaApiRepo', {
      repositoryName: 'nipuna-api',
      removalPolicy: cdk.RemovalPolicy.RETAIN,

      lifecycleRules: [
        {
          maxImageCount: 10,
        },
      ],
    });

    this.workerRepo = new ecr.Repository(this, 'NipunaWorkerRepo', {
      repositoryName: 'nipuna-worker',
      removalPolicy: cdk.RemovalPolicy.RETAIN,

      lifecycleRules: [
        {
          maxImageCount: 10,
        },
      ],
    });

    new cdk.CfnOutput(this, 'ApiRepoUri', {
      value: this.apiRepo.repositoryUri,
    });

    new cdk.CfnOutput(this, 'WorkerRepoUri', {
      value: this.workerRepo.repositoryUri,
    });
  }
}