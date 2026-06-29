"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.OpenSearchStack = void 0;
const cdk = __importStar(require("aws-cdk-lib"));
const opensearchserverless = __importStar(require("aws-cdk-lib/aws-opensearchserverless"));
class OpenSearchStack extends cdk.Stack {
    collectionEndpoint;
    constructor(scope, id, props) {
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
exports.OpenSearchStack = OpenSearchStack;
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoib3BlbnNlYXJjaC1zdGFjay5qcyIsInNvdXJjZVJvb3QiOiIiLCJzb3VyY2VzIjpbIm9wZW5zZWFyY2gtc3RhY2sudHMiXSwibmFtZXMiOltdLCJtYXBwaW5ncyI6Ijs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7O0FBQUEsaURBQW1DO0FBR25DLDJGQUE2RTtBQU83RSxNQUFhLGVBQWdCLFNBQVEsR0FBRyxDQUFDLEtBQUs7SUFDNUIsa0JBQWtCLENBQVM7SUFFM0MsWUFBWSxLQUFnQixFQUFFLEVBQVUsRUFBRSxLQUEyQjtRQUNuRSxLQUFLLENBQUMsS0FBSyxFQUFFLEVBQUUsRUFBRSxLQUFLLENBQUMsQ0FBQztRQUV4QixNQUFNLFVBQVUsR0FBRyxJQUFJLG9CQUFvQixDQUFDLGFBQWEsQ0FBQyxJQUFJLEVBQUUsZUFBZSxFQUFFO1lBQy9FLElBQUksRUFBRSxnQkFBZ0I7WUFDdEIsSUFBSSxFQUFFLGNBQWM7U0FDckIsQ0FBQyxDQUFDO1FBRUgsTUFBTSxnQkFBZ0IsR0FBRyxJQUFJLG9CQUFvQixDQUFDLGlCQUFpQixDQUFDLElBQUksRUFBRSx3QkFBd0IsRUFBRTtZQUNsRyxJQUFJLEVBQUUsMkJBQTJCO1lBQ2pDLElBQUksRUFBRSxZQUFZO1lBQ2xCLE1BQU0sRUFBRSxJQUFJLENBQUMsU0FBUyxDQUFDO2dCQUNyQixLQUFLLEVBQUU7b0JBQ0w7d0JBQ0UsUUFBUSxFQUFFLENBQUMsY0FBYyxVQUFVLENBQUMsSUFBSSxFQUFFLENBQUM7d0JBQzNDLFlBQVksRUFBRSxZQUFZO3FCQUMzQjtpQkFDRjtnQkFDRCxXQUFXLEVBQUUsSUFBSTthQUNsQixDQUFDO1NBQ0gsQ0FBQyxDQUFDO1FBRUgsTUFBTSxhQUFhLEdBQUcsSUFBSSxvQkFBb0IsQ0FBQyxpQkFBaUIsQ0FBQyxJQUFJLEVBQUUscUJBQXFCLEVBQUU7WUFDNUYsSUFBSSxFQUFFLHdCQUF3QjtZQUM5QixJQUFJLEVBQUUsU0FBUztZQUNmLE1BQU0sRUFBRSxJQUFJLENBQUMsU0FBUyxDQUFDO2dCQUNyQjtvQkFDRSxLQUFLLEVBQUU7d0JBQ0w7NEJBQ0UsUUFBUSxFQUFFLENBQUMsY0FBYyxVQUFVLENBQUMsSUFBSSxFQUFFLENBQUM7NEJBQzNDLFlBQVksRUFBRSxZQUFZO3lCQUMzQjtxQkFDRjtvQkFDRCxlQUFlLEVBQUUsSUFBSTtpQkFDdEI7YUFDRixDQUFDO1NBQ0gsQ0FBQyxDQUFDO1FBRUgsTUFBTSxnQkFBZ0IsR0FBRyxJQUFJLG9CQUFvQixDQUFDLGVBQWUsQ0FBQyxJQUFJLEVBQUUsd0JBQXdCLEVBQUU7WUFDaEcsSUFBSSxFQUFFLHVCQUF1QjtZQUM3QixJQUFJLEVBQUUsTUFBTTtZQUNaLE1BQU0sRUFBRSxJQUFJLENBQUMsU0FBUyxDQUFDO2dCQUNyQjtvQkFDRSxLQUFLLEVBQUU7d0JBQ0w7NEJBQ0UsUUFBUSxFQUFFLENBQUMsY0FBYyxVQUFVLENBQUMsSUFBSSxFQUFFLENBQUM7NEJBQzNDLFVBQVUsRUFBRTtnQ0FDViw0QkFBNEI7Z0NBQzVCLDRCQUE0QjtnQ0FDNUIsNEJBQTRCO2dDQUM1Qiw4QkFBOEI7NkJBQy9COzRCQUNELFlBQVksRUFBRSxZQUFZO3lCQUMzQjt3QkFDRDs0QkFDRSxRQUFRLEVBQUUsQ0FBQyxTQUFTLFVBQVUsQ0FBQyxJQUFJLElBQUksQ0FBQzs0QkFDeEMsVUFBVSxFQUFFO2dDQUNWLGtCQUFrQjtnQ0FDbEIsa0JBQWtCO2dDQUNsQixrQkFBa0I7Z0NBQ2xCLG9CQUFvQjtnQ0FDcEIsbUJBQW1CO2dDQUNuQixvQkFBb0I7NkJBQ3JCOzRCQUNELFlBQVksRUFBRSxPQUFPO3lCQUN0QjtxQkFDRjtvQkFDRCxTQUFTLEVBQUUsQ0FBQyxJQUFJLENBQUMsU0FBUyxDQUFDOzRCQUN6QixPQUFPLEVBQUUsS0FBSzs0QkFDZCxNQUFNLEVBQUUsRUFBRTs0QkFDVixPQUFPLEVBQUUsSUFBSSxDQUFDLE9BQU87NEJBQ3JCLFFBQVEsRUFBRSwyQkFBMkI7eUJBQ3RDLENBQUMsQ0FBQztpQkFDSjthQUNGLENBQUM7U0FDSCxDQUFDLENBQUM7UUFFSCxVQUFVLENBQUMsYUFBYSxDQUFDLGdCQUFnQixDQUFDLENBQUM7UUFDM0MsVUFBVSxDQUFDLGFBQWEsQ0FBQyxhQUFhLENBQUMsQ0FBQztRQUN4QyxVQUFVLENBQUMsYUFBYSxDQUFDLGdCQUFnQixDQUFDLENBQUM7UUFFM0MsSUFBSSxDQUFDLGtCQUFrQixHQUFHLFVBQVUsQ0FBQyxzQkFBc0IsQ0FBQztRQUU1RCxJQUFJLEdBQUcsQ0FBQyxTQUFTLENBQUMsSUFBSSxFQUFFLG9CQUFvQixFQUFFO1lBQzVDLEtBQUssRUFBRSxJQUFJLENBQUMsa0JBQWtCO1NBQy9CLENBQUMsQ0FBQztJQUNMLENBQUM7Q0FDRjtBQTFGRCwwQ0EwRkMiLCJzb3VyY2VzQ29udGVudCI6WyJpbXBvcnQgKiBhcyBjZGsgZnJvbSAnYXdzLWNkay1saWInO1xuaW1wb3J0IHsgQ29uc3RydWN0IH0gZnJvbSAnY29uc3RydWN0cyc7XG5pbXBvcnQgKiBhcyBlYzIgZnJvbSAnYXdzLWNkay1saWIvYXdzLWVjMic7XG5pbXBvcnQgKiBhcyBvcGVuc2VhcmNoc2VydmVybGVzcyBmcm9tICdhd3MtY2RrLWxpYi9hd3Mtb3BlbnNlYXJjaHNlcnZlcmxlc3MnO1xuaW1wb3J0ICogYXMgaWFtIGZyb20gJ2F3cy1jZGstbGliL2F3cy1pYW0nO1xuXG5pbnRlcmZhY2UgT3BlblNlYXJjaFN0YWNrUHJvcHMgZXh0ZW5kcyBjZGsuU3RhY2tQcm9wcyB7XG4gIHZwYzogZWMyLlZwYztcbn1cblxuZXhwb3J0IGNsYXNzIE9wZW5TZWFyY2hTdGFjayBleHRlbmRzIGNkay5TdGFjayB7XG4gIHB1YmxpYyByZWFkb25seSBjb2xsZWN0aW9uRW5kcG9pbnQ6IHN0cmluZztcblxuICBjb25zdHJ1Y3RvcihzY29wZTogQ29uc3RydWN0LCBpZDogc3RyaW5nLCBwcm9wczogT3BlblNlYXJjaFN0YWNrUHJvcHMpIHtcbiAgICBzdXBlcihzY29wZSwgaWQsIHByb3BzKTtcblxuICAgIGNvbnN0IGNvbGxlY3Rpb24gPSBuZXcgb3BlbnNlYXJjaHNlcnZlcmxlc3MuQ2ZuQ29sbGVjdGlvbih0aGlzLCAnTmlwdW5hVmVjdG9ycycsIHtcbiAgICAgIG5hbWU6ICduaXB1bmEtdmVjdG9ycycsXG4gICAgICB0eXBlOiAnVkVDVE9SU0VBUkNIJyxcbiAgICB9KTtcblxuICAgIGNvbnN0IGVuY3J5cHRpb25Qb2xpY3kgPSBuZXcgb3BlbnNlYXJjaHNlcnZlcmxlc3MuQ2ZuU2VjdXJpdHlQb2xpY3kodGhpcywgJ1ZlY3RvckVuY3J5cHRpb25Qb2xpY3knLCB7XG4gICAgICBuYW1lOiAnbmlwdW5hLXZlY3RvcnMtZW5jcnlwdGlvbicsXG4gICAgICB0eXBlOiAnZW5jcnlwdGlvbicsXG4gICAgICBwb2xpY3k6IEpTT04uc3RyaW5naWZ5KHtcbiAgICAgICAgUnVsZXM6IFtcbiAgICAgICAgICB7XG4gICAgICAgICAgICBSZXNvdXJjZTogW2Bjb2xsZWN0aW9uLyR7Y29sbGVjdGlvbi5uYW1lfWBdLFxuICAgICAgICAgICAgUmVzb3VyY2VUeXBlOiAnY29sbGVjdGlvbicsXG4gICAgICAgICAgfSxcbiAgICAgICAgXSxcbiAgICAgICAgQVdTT3duZWRLZXk6IHRydWUsXG4gICAgICB9KSxcbiAgICB9KTtcblxuICAgIGNvbnN0IG5ldHdvcmtQb2xpY3kgPSBuZXcgb3BlbnNlYXJjaHNlcnZlcmxlc3MuQ2ZuU2VjdXJpdHlQb2xpY3kodGhpcywgJ1ZlY3Rvck5ldHdvcmtQb2xpY3knLCB7XG4gICAgICBuYW1lOiAnbmlwdW5hLXZlY3RvcnMtbmV0d29yaycsXG4gICAgICB0eXBlOiAnbmV0d29yaycsXG4gICAgICBwb2xpY3k6IEpTT04uc3RyaW5naWZ5KFtcbiAgICAgICAge1xuICAgICAgICAgIFJ1bGVzOiBbXG4gICAgICAgICAgICB7XG4gICAgICAgICAgICAgIFJlc291cmNlOiBbYGNvbGxlY3Rpb24vJHtjb2xsZWN0aW9uLm5hbWV9YF0sXG4gICAgICAgICAgICAgIFJlc291cmNlVHlwZTogJ2NvbGxlY3Rpb24nLFxuICAgICAgICAgICAgfSxcbiAgICAgICAgICBdLFxuICAgICAgICAgIEFsbG93RnJvbVB1YmxpYzogdHJ1ZSxcbiAgICAgICAgfSxcbiAgICAgIF0pLFxuICAgIH0pO1xuXG4gICAgY29uc3QgZGF0YUFjY2Vzc1BvbGljeSA9IG5ldyBvcGVuc2VhcmNoc2VydmVybGVzcy5DZm5BY2Nlc3NQb2xpY3kodGhpcywgJ1ZlY3RvckRhdGFBY2Nlc3NQb2xpY3knLCB7XG4gICAgICBuYW1lOiAnbmlwdW5hLXZlY3RvcnMtYWNjZXNzJyxcbiAgICAgIHR5cGU6ICdkYXRhJyxcbiAgICAgIHBvbGljeTogSlNPTi5zdHJpbmdpZnkoW1xuICAgICAgICB7XG4gICAgICAgICAgUnVsZXM6IFtcbiAgICAgICAgICAgIHtcbiAgICAgICAgICAgICAgUmVzb3VyY2U6IFtgY29sbGVjdGlvbi8ke2NvbGxlY3Rpb24ubmFtZX1gXSxcbiAgICAgICAgICAgICAgUGVybWlzc2lvbjogW1xuICAgICAgICAgICAgICAgICdhb3NzOkNyZWF0ZUNvbGxlY3Rpb25JdGVtcycsXG4gICAgICAgICAgICAgICAgJ2Fvc3M6RGVsZXRlQ29sbGVjdGlvbkl0ZW1zJyxcbiAgICAgICAgICAgICAgICAnYW9zczpVcGRhdGVDb2xsZWN0aW9uSXRlbXMnLFxuICAgICAgICAgICAgICAgICdhb3NzOkRlc2NyaWJlQ29sbGVjdGlvbkl0ZW1zJyxcbiAgICAgICAgICAgICAgXSxcbiAgICAgICAgICAgICAgUmVzb3VyY2VUeXBlOiAnY29sbGVjdGlvbicsXG4gICAgICAgICAgICB9LFxuICAgICAgICAgICAge1xuICAgICAgICAgICAgICBSZXNvdXJjZTogW2BpbmRleC8ke2NvbGxlY3Rpb24ubmFtZX0vKmBdLFxuICAgICAgICAgICAgICBQZXJtaXNzaW9uOiBbXG4gICAgICAgICAgICAgICAgJ2Fvc3M6Q3JlYXRlSW5kZXgnLFxuICAgICAgICAgICAgICAgICdhb3NzOkRlbGV0ZUluZGV4JyxcbiAgICAgICAgICAgICAgICAnYW9zczpVcGRhdGVJbmRleCcsXG4gICAgICAgICAgICAgICAgJ2Fvc3M6RGVzY3JpYmVJbmRleCcsXG4gICAgICAgICAgICAgICAgJ2Fvc3M6UmVhZERvY3VtZW50JyxcbiAgICAgICAgICAgICAgICAnYW9zczpXcml0ZURvY3VtZW50JyxcbiAgICAgICAgICAgICAgXSxcbiAgICAgICAgICAgICAgUmVzb3VyY2VUeXBlOiAnaW5kZXgnLFxuICAgICAgICAgICAgfSxcbiAgICAgICAgICBdLFxuICAgICAgICAgIFByaW5jaXBhbDogW3RoaXMuZm9ybWF0QXJuKHtcbiAgICAgICAgICAgIHNlcnZpY2U6ICdpYW0nLFxuICAgICAgICAgICAgcmVnaW9uOiAnJyxcbiAgICAgICAgICAgIGFjY291bnQ6IHRoaXMuYWNjb3VudCxcbiAgICAgICAgICAgIHJlc291cmNlOiAncm9sZS9uaXB1bmEtZWNzLXRhc2stcm9sZScsXG4gICAgICAgICAgfSldLFxuICAgICAgICB9LFxuICAgICAgXSksXG4gICAgfSk7XG5cbiAgICBjb2xsZWN0aW9uLmFkZERlcGVuZGVuY3koZW5jcnlwdGlvblBvbGljeSk7XG4gICAgY29sbGVjdGlvbi5hZGREZXBlbmRlbmN5KG5ldHdvcmtQb2xpY3kpO1xuICAgIGNvbGxlY3Rpb24uYWRkRGVwZW5kZW5jeShkYXRhQWNjZXNzUG9saWN5KTtcblxuICAgIHRoaXMuY29sbGVjdGlvbkVuZHBvaW50ID0gY29sbGVjdGlvbi5hdHRyQ29sbGVjdGlvbkVuZHBvaW50O1xuXG4gICAgbmV3IGNkay5DZm5PdXRwdXQodGhpcywgJ0NvbGxlY3Rpb25FbmRwb2ludCcsIHtcbiAgICAgIHZhbHVlOiB0aGlzLmNvbGxlY3Rpb25FbmRwb2ludCxcbiAgICB9KTtcbiAgfVxufVxuIl19