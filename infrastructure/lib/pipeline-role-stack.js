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
exports.PipelineRoleStack = void 0;
const cdk = __importStar(require("aws-cdk-lib"));
const iam = __importStar(require("aws-cdk-lib/aws-iam"));
class PipelineRoleStack extends cdk.Stack {
    roleArn;
    constructor(scope, id, props) {
        super(scope, id, props);
        // Get GitHub Org/Repo from context, default to the user's backend repo
        const githubOrg = this.node.tryGetContext('githubOrg') || 'bhavuk1409';
        const githubRepo = this.node.tryGetContext('githubRepo') || 'nipuna-ai-backend';
        // 1. GitHub OIDC Provider setup (conditional on context to avoid duplicates)
        let provider;
        const existingProviderArn = this.node.tryGetContext('githubOidcProviderArn');
        if (existingProviderArn) {
            provider = iam.OpenIdConnectProvider.fromOpenIdConnectProviderArn(this, 'GithubOidcProvider', existingProviderArn);
        }
        else {
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
exports.PipelineRoleStack = PipelineRoleStack;
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoicGlwZWxpbmUtcm9sZS1zdGFjay5qcyIsInNvdXJjZVJvb3QiOiIiLCJzb3VyY2VzIjpbInBpcGVsaW5lLXJvbGUtc3RhY2sudHMiXSwibmFtZXMiOltdLCJtYXBwaW5ncyI6Ijs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7O0FBQUEsaURBQW1DO0FBRW5DLHlEQUEyQztBQVczQyxNQUFhLGlCQUFrQixTQUFRLEdBQUcsQ0FBQyxLQUFLO0lBQzlCLE9BQU8sQ0FBUztJQUVoQyxZQUFZLEtBQWdCLEVBQUUsRUFBVSxFQUFFLEtBQTZCO1FBQ3JFLEtBQUssQ0FBQyxLQUFLLEVBQUUsRUFBRSxFQUFFLEtBQUssQ0FBQyxDQUFDO1FBRXhCLHVFQUF1RTtRQUN2RSxNQUFNLFNBQVMsR0FBRyxJQUFJLENBQUMsSUFBSSxDQUFDLGFBQWEsQ0FBQyxXQUFXLENBQUMsSUFBSSxZQUFZLENBQUM7UUFDdkUsTUFBTSxVQUFVLEdBQUcsSUFBSSxDQUFDLElBQUksQ0FBQyxhQUFhLENBQUMsWUFBWSxDQUFDLElBQUksbUJBQW1CLENBQUM7UUFFaEYsNkVBQTZFO1FBQzdFLElBQUksUUFBb0MsQ0FBQztRQUN6QyxNQUFNLG1CQUFtQixHQUFHLElBQUksQ0FBQyxJQUFJLENBQUMsYUFBYSxDQUFDLHVCQUF1QixDQUFDLENBQUM7UUFFN0UsSUFBSSxtQkFBbUIsRUFBRSxDQUFDO1lBQ3hCLFFBQVEsR0FBRyxHQUFHLENBQUMscUJBQXFCLENBQUMsNEJBQTRCLENBQUMsSUFBSSxFQUFFLG9CQUFvQixFQUFFLG1CQUFtQixDQUFDLENBQUM7UUFDckgsQ0FBQzthQUFNLENBQUM7WUFDTixRQUFRLEdBQUcsSUFBSSxHQUFHLENBQUMscUJBQXFCLENBQUMsSUFBSSxFQUFFLG9CQUFvQixFQUFFO2dCQUNuRSxHQUFHLEVBQUUsNkNBQTZDO2dCQUNsRCxTQUFTLEVBQUUsQ0FBQyxtQkFBbUIsQ0FBQzthQUNqQyxDQUFDLENBQUM7UUFDTCxDQUFDO1FBRUQsK0NBQStDO1FBQy9DLE1BQU0sVUFBVSxHQUFHLElBQUksR0FBRyxDQUFDLElBQUksQ0FBQyxJQUFJLEVBQUUsa0JBQWtCLEVBQUU7WUFDeEQsUUFBUSxFQUFFLDJCQUEyQjtZQUNyQyxTQUFTLEVBQUUsSUFBSSxHQUFHLENBQUMsb0JBQW9CLENBQUMsUUFBUSxDQUFDLHdCQUF3QixFQUFFO2dCQUN6RSxZQUFZLEVBQUU7b0JBQ1oseUNBQXlDLEVBQUUsbUJBQW1CO2lCQUMvRDtnQkFDRCxVQUFVLEVBQUU7b0JBQ1YseUNBQXlDLEVBQUUsUUFBUSxTQUFTLElBQUksVUFBVSxJQUFJO2lCQUMvRTthQUNGLENBQUM7WUFDRixXQUFXLEVBQUUsMEVBQTBFO1NBQ3hGLENBQUMsQ0FBQztRQUVILHVFQUF1RTtRQUN2RSxVQUFVLENBQUMsV0FBVyxDQUFDLElBQUksR0FBRyxDQUFDLGVBQWUsQ0FBQztZQUM3QyxPQUFPLEVBQUUsQ0FBQywyQkFBMkIsQ0FBQztZQUN0QyxTQUFTLEVBQUUsQ0FBQyxHQUFHLENBQUM7U0FDakIsQ0FBQyxDQUFDLENBQUM7UUFFSiwrREFBK0Q7UUFDL0QsS0FBSyxDQUFDLE9BQU8sQ0FBQyxhQUFhLENBQUMsVUFBVSxDQUFDLENBQUM7UUFDeEMsS0FBSyxDQUFDLFVBQVUsQ0FBQyxhQUFhLENBQUMsVUFBVSxDQUFDLENBQUM7UUFFM0MseURBQXlEO1FBQ3pELFVBQVUsQ0FBQyxXQUFXLENBQUMsSUFBSSxHQUFHLENBQUMsZUFBZSxDQUFDO1lBQzdDLE9BQU8sRUFBRTtnQkFDUCxtQkFBbUI7Z0JBQ25CLHNCQUFzQjthQUN2QjtZQUNELFNBQVMsRUFBRTtnQkFDVCxLQUFLLENBQUMsYUFBYTtnQkFDbkIsS0FBSyxDQUFDLGdCQUFnQjthQUN2QjtTQUNGLENBQUMsQ0FBQyxDQUFDO1FBRUosc0JBQXNCO1FBQ3RCLElBQUksQ0FBQyxPQUFPLEdBQUcsVUFBVSxDQUFDLE9BQU8sQ0FBQztRQUNsQyxJQUFJLEdBQUcsQ0FBQyxTQUFTLENBQUMsSUFBSSxFQUFFLHFCQUFxQixFQUFFO1lBQzdDLEtBQUssRUFBRSxVQUFVLENBQUMsT0FBTztZQUN6QixXQUFXLEVBQUUseUdBQXlHO1NBQ3ZILENBQUMsQ0FBQztJQUNMLENBQUM7Q0FDRjtBQWxFRCw4Q0FrRUMiLCJzb3VyY2VzQ29udGVudCI6WyJpbXBvcnQgKiBhcyBjZGsgZnJvbSAnYXdzLWNkay1saWInO1xuaW1wb3J0IHsgQ29uc3RydWN0IH0gZnJvbSAnY29uc3RydWN0cyc7XG5pbXBvcnQgKiBhcyBpYW0gZnJvbSAnYXdzLWNkay1saWIvYXdzLWlhbSc7XG5pbXBvcnQgKiBhcyBlY3IgZnJvbSAnYXdzLWNkay1saWIvYXdzLWVjcic7XG5cbmludGVyZmFjZSBQaXBlbGluZVJvbGVTdGFja1Byb3BzIGV4dGVuZHMgY2RrLlN0YWNrUHJvcHMge1xuICBhcGlSZXBvOiBlY3IuUmVwb3NpdG9yeTtcbiAgd29ya2VyUmVwbzogZWNyLlJlcG9zaXRvcnk7XG4gIGVjc0NsdXN0ZXJBcm46IHN0cmluZztcbiAgYXBpU2VydmljZUFybjogc3RyaW5nO1xuICB3b3JrZXJTZXJ2aWNlQXJuOiBzdHJpbmc7XG59XG5cbmV4cG9ydCBjbGFzcyBQaXBlbGluZVJvbGVTdGFjayBleHRlbmRzIGNkay5TdGFjayB7XG4gIHB1YmxpYyByZWFkb25seSByb2xlQXJuOiBzdHJpbmc7XG5cbiAgY29uc3RydWN0b3Ioc2NvcGU6IENvbnN0cnVjdCwgaWQ6IHN0cmluZywgcHJvcHM6IFBpcGVsaW5lUm9sZVN0YWNrUHJvcHMpIHtcbiAgICBzdXBlcihzY29wZSwgaWQsIHByb3BzKTtcblxuICAgIC8vIEdldCBHaXRIdWIgT3JnL1JlcG8gZnJvbSBjb250ZXh0LCBkZWZhdWx0IHRvIHRoZSB1c2VyJ3MgYmFja2VuZCByZXBvXG4gICAgY29uc3QgZ2l0aHViT3JnID0gdGhpcy5ub2RlLnRyeUdldENvbnRleHQoJ2dpdGh1Yk9yZycpIHx8ICdiaGF2dWsxNDA5JztcbiAgICBjb25zdCBnaXRodWJSZXBvID0gdGhpcy5ub2RlLnRyeUdldENvbnRleHQoJ2dpdGh1YlJlcG8nKSB8fCAnbmlwdW5hLWFpLWJhY2tlbmQnO1xuXG4gICAgLy8gMS4gR2l0SHViIE9JREMgUHJvdmlkZXIgc2V0dXAgKGNvbmRpdGlvbmFsIG9uIGNvbnRleHQgdG8gYXZvaWQgZHVwbGljYXRlcylcbiAgICBsZXQgcHJvdmlkZXI6IGlhbS5JT3BlbklkQ29ubmVjdFByb3ZpZGVyO1xuICAgIGNvbnN0IGV4aXN0aW5nUHJvdmlkZXJBcm4gPSB0aGlzLm5vZGUudHJ5R2V0Q29udGV4dCgnZ2l0aHViT2lkY1Byb3ZpZGVyQXJuJyk7XG4gICAgXG4gICAgaWYgKGV4aXN0aW5nUHJvdmlkZXJBcm4pIHtcbiAgICAgIHByb3ZpZGVyID0gaWFtLk9wZW5JZENvbm5lY3RQcm92aWRlci5mcm9tT3BlbklkQ29ubmVjdFByb3ZpZGVyQXJuKHRoaXMsICdHaXRodWJPaWRjUHJvdmlkZXInLCBleGlzdGluZ1Byb3ZpZGVyQXJuKTtcbiAgICB9IGVsc2Uge1xuICAgICAgcHJvdmlkZXIgPSBuZXcgaWFtLk9wZW5JZENvbm5lY3RQcm92aWRlcih0aGlzLCAnR2l0aHViT2lkY1Byb3ZpZGVyJywge1xuICAgICAgICB1cmw6ICdodHRwczovL3Rva2VuLmFjdGlvbnMuZ2l0aHVidXNlcmNvbnRlbnQuY29tJyxcbiAgICAgICAgY2xpZW50SWRzOiBbJ3N0cy5hbWF6b25hd3MuY29tJ10sXG4gICAgICB9KTtcbiAgICB9XG5cbiAgICAvLyAyLiBDcmVhdGUgdGhlIEdpdEh1YiBBY3Rpb25zIGRlcGxveW1lbnQgcm9sZVxuICAgIGNvbnN0IGRlcGxveVJvbGUgPSBuZXcgaWFtLlJvbGUodGhpcywgJ0dpdGh1YkRlcGxveVJvbGUnLCB7XG4gICAgICByb2xlTmFtZTogJ25pcHVuYS1naXRodWItZGVwbG95LXJvbGUnLFxuICAgICAgYXNzdW1lZEJ5OiBuZXcgaWFtLldlYklkZW50aXR5UHJpbmNpcGFsKHByb3ZpZGVyLm9wZW5JZENvbm5lY3RQcm92aWRlckFybiwge1xuICAgICAgICBTdHJpbmdFcXVhbHM6IHtcbiAgICAgICAgICAndG9rZW4uYWN0aW9ucy5naXRodWJ1c2VyY29udGVudC5jb206YXVkJzogJ3N0cy5hbWF6b25hd3MuY29tJyxcbiAgICAgICAgfSxcbiAgICAgICAgU3RyaW5nTGlrZToge1xuICAgICAgICAgICd0b2tlbi5hY3Rpb25zLmdpdGh1YnVzZXJjb250ZW50LmNvbTpzdWInOiBgcmVwbzoke2dpdGh1Yk9yZ30vJHtnaXRodWJSZXBvfToqYCxcbiAgICAgICAgfSxcbiAgICAgIH0pLFxuICAgICAgZGVzY3JpcHRpb246ICdJQU0gUm9sZSBhc3N1bWVkIGJ5IEdpdEh1YiBBY3Rpb25zIGZvciBkZXBsb3lpbmcgTmlwdW5hIEJhY2tlbmQgc2VydmljZXMnLFxuICAgIH0pO1xuXG4gICAgLy8gMy4gR3JhbnQgRUNSIGF1dGhvcml6YXRpb24gcGVybWlzc2lvbnMgKFJlcXVpcmVkIHRvIGdldCBsb2dpbiB0b2tlbilcbiAgICBkZXBsb3lSb2xlLmFkZFRvUG9saWN5KG5ldyBpYW0uUG9saWN5U3RhdGVtZW50KHtcbiAgICAgIGFjdGlvbnM6IFsnZWNyOkdldEF1dGhvcml6YXRpb25Ub2tlbiddLFxuICAgICAgcmVzb3VyY2VzOiBbJyonXSxcbiAgICB9KSk7XG5cbiAgICAvLyA0LiBHcmFudCBwdXNoL3B1bGwgYWNjZXNzIHRvIHRoZSBBUEkgYW5kIFdvcmtlciByZXBvc2l0b3JpZXNcbiAgICBwcm9wcy5hcGlSZXBvLmdyYW50UHVsbFB1c2goZGVwbG95Um9sZSk7XG4gICAgcHJvcHMud29ya2VyUmVwby5ncmFudFB1bGxQdXNoKGRlcGxveVJvbGUpO1xuXG4gICAgLy8gNS4gR3JhbnQgRUNTIGRlcGxveW1lbnQgcGVybWlzc2lvbnMgdG8gdXBkYXRlIHNlcnZpY2VzXG4gICAgZGVwbG95Um9sZS5hZGRUb1BvbGljeShuZXcgaWFtLlBvbGljeVN0YXRlbWVudCh7XG4gICAgICBhY3Rpb25zOiBbXG4gICAgICAgICdlY3M6VXBkYXRlU2VydmljZScsXG4gICAgICAgICdlY3M6RGVzY3JpYmVTZXJ2aWNlcycsXG4gICAgICBdLFxuICAgICAgcmVzb3VyY2VzOiBbXG4gICAgICAgIHByb3BzLmFwaVNlcnZpY2VBcm4sXG4gICAgICAgIHByb3BzLndvcmtlclNlcnZpY2VBcm4sXG4gICAgICBdLFxuICAgIH0pKTtcblxuICAgIC8vIE91dHB1dCB0aGUgUm9sZSBBUk5cbiAgICB0aGlzLnJvbGVBcm4gPSBkZXBsb3lSb2xlLnJvbGVBcm47XG4gICAgbmV3IGNkay5DZm5PdXRwdXQodGhpcywgJ0dpdGh1YkRlcGxveVJvbGVBcm4nLCB7XG4gICAgICB2YWx1ZTogZGVwbG95Um9sZS5yb2xlQXJuLFxuICAgICAgZGVzY3JpcHRpb246ICdBUk4gb2YgdGhlIElBTSBSb2xlIGZvciBHaXRIdWIgQWN0aW9ucyBkZXBsb3ltZW50IChwYXN0ZSB0aGlzIGluIEdpdEh1YiBzZWNyZXRzIGFzIEFXU19ERVBMT1lfUk9MRV9BUk4pJyxcbiAgICB9KTtcbiAgfVxufVxuIl19