import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as ecr from 'aws-cdk-lib/aws-ecr';

interface PipelineRoleStackProps extends cdk.StackProps {
  apiRepo: ecr.Repository;
  workerRepo: ecr.Repository;
  ecsClusterArn: string;
  apiServiceArn: string;
  workerServiceArn: string;
}

export class PipelineRoleStack extends cdk.Stack {
  public readonly roleArn: string;

  constructor(scope: Construct, id: string, props: PipelineRoleStackProps) {
    super(scope, id, props);

    // Get GitHub Org/Repo from context, default to the user's backend repo
    const githubOrg = this.node.tryGetContext('githubOrg') || 'bhavuk1409';
    const githubRepo = this.node.tryGetContext('githubRepo') || 'nipuna-ai-backend';

    // 1. GitHub OIDC Provider setup (conditional on context to avoid duplicates)
    let provider: iam.IOpenIdConnectProvider;
    const existingProviderArn = this.node.tryGetContext('githubOidcProviderArn');
    
    if (existingProviderArn) {
      provider = iam.OpenIdConnectProvider.fromOpenIdConnectProviderArn(this, 'GithubOidcProvider', existingProviderArn);
    } else {
      provider = new iam.OpenIdConnectProvider(this, 'GithubOidcProvider', {
        url: 'https://token.actions.githubusercontent.com',
        clientIds: ['sts.amazonaws.com'],
      });
    }

    // 2. Create the GitHub Actions deployment role
    const deployRole = new iam.Role(this, 'GithubDeployRole', {
      roleName: 'nipuna-github-deploy-role',
      assumedBy: new iam.WebIdentityPrincipal(provider.openIdConnectProviderArn, {
        StringEquals: {
          'token.actions.githubusercontent.com:aud': 'sts.amazonaws.com',
        },
        StringLike: {
          'token.actions.githubusercontent.com:sub': `repo:${githubOrg}/${githubRepo}:*`,
        },
      }),
      description: 'IAM Role assumed by GitHub Actions for deploying Nipuna Backend services',
    });

    // 3. Grant ECR authorization permissions (Required to get login token)
    deployRole.addToPolicy(new iam.PolicyStatement({
      actions: ['ecr:GetAuthorizationToken'],
      resources: ['*'],
    }));

    // 4. Grant push/pull access to the API and Worker repositories
    props.apiRepo.grantPullPush(deployRole);
    props.workerRepo.grantPullPush(deployRole);

    // 5. Grant ECS deployment permissions to update services
    deployRole.addToPolicy(new iam.PolicyStatement({
      actions: [
        'ecs:UpdateService',
        'ecs:DescribeServices',
      ],
      resources: [
        props.apiServiceArn,
        props.workerServiceArn,
      ],
    }));

    // Output the Role ARN
    this.roleArn = deployRole.roleArn;
    new cdk.CfnOutput(this, 'GithubDeployRoleArn', {
      value: deployRole.roleArn,
      description: 'ARN of the IAM Role for GitHub Actions deployment (paste this in GitHub secrets as AWS_DEPLOY_ROLE_ARN)',
    });
  }
}
