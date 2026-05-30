import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as opensearchserverless from 'aws-cdk-lib/aws-opensearchserverless';
import * as iam from 'aws-cdk-lib/aws-iam';

interface OpenSearchStackProps extends cdk.StackProps {
  vpc: ec2.Vpc;
}

export class OpenSearchStack extends cdk.Stack {
  public readonly collectionEndpoint: string;

  constructor(scope: Construct, id: string, props: OpenSearchStackProps) {
    super(scope, id, props);

    const collection = new opensearchserverless.CfnCollection(this, 'NipunaVectors', {
      name: 'nipuna-vectors',
      type: 'VECTORSEARCH',
    });

    const encryptionPolicy = new opensearchserverless.CfnSecurityPolicy(this, 'VectorEncryptionPolicy', {
      name: 'nipuna-vectors-encryption',
      type: 'encryption',
      policy: JSON.stringify({
        Rules: [
          {
            Resource: [`collection/${collection.name}`],
            ResourceType: 'collection',
          },
        ],
        AWSOwnedKey: true,
      }),
    });

    const networkPolicy = new opensearchserverless.CfnSecurityPolicy(this, 'VectorNetworkPolicy', {
      name: 'nipuna-vectors-network',
      type: 'network',
      policy: JSON.stringify([
        {
          Rules: [
            {
              Resource: [`collection/${collection.name}`],
              ResourceType: 'collection',
            },
          ],
          AllowFromPublic: true,
        },
      ]),
    });

    const dataAccessPolicy = new opensearchserverless.CfnAccessPolicy(this, 'VectorDataAccessPolicy', {
      name: 'nipuna-vectors-access',
      type: 'data',
      policy: JSON.stringify([
        {
          Rules: [
            {
              Resource: [`collection/${collection.name}`],
              Permission: [
                'aoss:CreateCollectionItems',
                'aoss:DeleteCollectionItems',
                'aoss:UpdateCollectionItems',
                'aoss:DescribeCollectionItems',
              ],
              ResourceType: 'collection',
            },
            {
              Resource: [`index/${collection.name}/*`],
              Permission: [
                'aoss:CreateIndex',
                'aoss:DeleteIndex',
                'aoss:UpdateIndex',
                'aoss:DescribeIndex',
                'aoss:ReadDocument',
                'aoss:WriteDocument',
              ],
              ResourceType: 'index',
            },
          ],
          Principal: [this.formatArn({
            service: 'iam',
            region: '',
            account: this.account,
            resource: 'role/nipuna-ecs-task-role',
          })],
        },
      ]),
    });

    collection.addDependency(encryptionPolicy);
    collection.addDependency(networkPolicy);
    collection.addDependency(dataAccessPolicy);

    this.collectionEndpoint = collection.attrCollectionEndpoint;

    new cdk.CfnOutput(this, 'CollectionEndpoint', {
      value: this.collectionEndpoint,
    });
  }
}
