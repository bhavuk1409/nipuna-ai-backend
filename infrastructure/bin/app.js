#!/usr/bin/env node
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
const cdk = __importStar(require("aws-cdk-lib"));
const vpc_stack_1 = require("../lib/vpc-stack");
const rds_stack_1 = require("../lib/rds-stack");
const elasticache_stack_1 = require("../lib/elasticache-stack");
const opensearch_stack_1 = require("../lib/opensearch-stack");
const ecr_stack_1 = require("../lib/ecr-stack");
const ecs_stack_1 = require("../lib/ecs-stack");
const pipeline_role_stack_1 = require("../lib/pipeline-role-stack");
const app = new cdk.App();
const env = {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: 'ap-south-1',
};
const vpcStack = new vpc_stack_1.VpcStack(app, 'VpcStack', { env });
const rdsStack = new rds_stack_1.RdsStack(app, 'RdsStack', {
    env,
    vpc: vpcStack.vpc,
    rdsSg: vpcStack.rdsSg,
});
const elasticacheStack = new elasticache_stack_1.ElastiCacheStack(app, 'ElastiCacheStack', {
    env,
    vpc: vpcStack.vpc,
});
const openSearchStack = new opensearch_stack_1.OpenSearchStack(app, 'OpenSearchStack', {
    env,
    vpc: vpcStack.vpc,
});
const ecrStack = new ecr_stack_1.EcrStack(app, 'EcrStack', { env });
const ecsStack = new ecs_stack_1.EcsStack(app, 'EcsStack', {
    env,
    vpc: vpcStack.vpc,
    apiRepo: ecrStack.apiRepo,
    workerRepo: ecrStack.workerRepo,
    databaseSecret: rdsStack.databaseSecret,
    databaseEndpoint: rdsStack.databaseEndpoint,
    redisEndpoint: elasticacheStack.primaryEndpoint,
    openSearchEndpoint: openSearchStack.collectionEndpoint,
    rdsSg: vpcStack.rdsSg,
    redisSg: elasticacheStack.redisSg,
});
rdsStack.addDependency(vpcStack);
elasticacheStack.addDependency(vpcStack);
openSearchStack.addDependency(vpcStack);
ecsStack.addDependency(ecrStack);
ecsStack.addDependency(rdsStack);
ecsStack.addDependency(elasticacheStack);
ecsStack.addDependency(openSearchStack);
const pipelineRoleStack = new pipeline_role_stack_1.PipelineRoleStack(app, 'PipelineRoleStack', {
    env,
    apiRepo: ecrStack.apiRepo,
    workerRepo: ecrStack.workerRepo,
    ecsClusterArn: ecsStack.clusterArn,
    apiServiceArn: ecsStack.apiServiceArn,
    workerServiceArn: ecsStack.workerServiceArn,
});
pipelineRoleStack.addDependency(ecrStack);
pipelineRoleStack.addDependency(ecsStack);
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoiYXBwLmpzIiwic291cmNlUm9vdCI6IiIsInNvdXJjZXMiOlsiYXBwLnRzIl0sIm5hbWVzIjpbXSwibWFwcGluZ3MiOiI7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7OztBQUNBLGlEQUFtQztBQUNuQyxnREFBNEM7QUFDNUMsZ0RBQTRDO0FBQzVDLGdFQUE0RDtBQUM1RCw4REFBMEQ7QUFDMUQsZ0RBQTRDO0FBQzVDLGdEQUE0QztBQUM1QyxvRUFBK0Q7QUFFL0QsTUFBTSxHQUFHLEdBQUcsSUFBSSxHQUFHLENBQUMsR0FBRyxFQUFFLENBQUM7QUFFMUIsTUFBTSxHQUFHLEdBQUc7SUFDVixPQUFPLEVBQUUsT0FBTyxDQUFDLEdBQUcsQ0FBQyxtQkFBbUI7SUFDeEMsTUFBTSxFQUFFLFlBQVk7Q0FDckIsQ0FBQztBQUVGLE1BQU0sUUFBUSxHQUFHLElBQUksb0JBQVEsQ0FBQyxHQUFHLEVBQUUsVUFBVSxFQUFFLEVBQUUsR0FBRyxFQUFFLENBQUMsQ0FBQztBQUV4RCxNQUFNLFFBQVEsR0FBRyxJQUFJLG9CQUFRLENBQUMsR0FBRyxFQUFFLFVBQVUsRUFBRTtJQUM3QyxHQUFHO0lBQ0gsR0FBRyxFQUFFLFFBQVEsQ0FBQyxHQUFHO0lBQ2pCLEtBQUssRUFBRSxRQUFRLENBQUMsS0FBSztDQUN0QixDQUFDLENBQUM7QUFFSCxNQUFNLGdCQUFnQixHQUFHLElBQUksb0NBQWdCLENBQUMsR0FBRyxFQUFFLGtCQUFrQixFQUFFO0lBQ3JFLEdBQUc7SUFDSCxHQUFHLEVBQUUsUUFBUSxDQUFDLEdBQUc7Q0FDbEIsQ0FBQyxDQUFDO0FBRUgsTUFBTSxlQUFlLEdBQUcsSUFBSSxrQ0FBZSxDQUFDLEdBQUcsRUFBRSxpQkFBaUIsRUFBRTtJQUNsRSxHQUFHO0lBQ0gsR0FBRyxFQUFFLFFBQVEsQ0FBQyxHQUFHO0NBQ2xCLENBQUMsQ0FBQztBQUVILE1BQU0sUUFBUSxHQUFHLElBQUksb0JBQVEsQ0FBQyxHQUFHLEVBQUUsVUFBVSxFQUFFLEVBQUUsR0FBRyxFQUFFLENBQUMsQ0FBQztBQUV4RCxNQUFNLFFBQVEsR0FBRyxJQUFJLG9CQUFRLENBQUMsR0FBRyxFQUFFLFVBQVUsRUFBRTtJQUM3QyxHQUFHO0lBQ0gsR0FBRyxFQUFFLFFBQVEsQ0FBQyxHQUFHO0lBQ2pCLE9BQU8sRUFBRSxRQUFRLENBQUMsT0FBTztJQUN6QixVQUFVLEVBQUUsUUFBUSxDQUFDLFVBQVU7SUFDL0IsY0FBYyxFQUFFLFFBQVEsQ0FBQyxjQUFjO0lBQ3ZDLGdCQUFnQixFQUFFLFFBQVEsQ0FBQyxnQkFBZ0I7SUFDM0MsYUFBYSxFQUFFLGdCQUFnQixDQUFDLGVBQWU7SUFDL0Msa0JBQWtCLEVBQUUsZUFBZSxDQUFDLGtCQUFrQjtJQUN0RCxLQUFLLEVBQUUsUUFBUSxDQUFDLEtBQUs7SUFDckIsT0FBTyxFQUFFLGdCQUFnQixDQUFDLE9BQU87Q0FDbEMsQ0FBQyxDQUFDO0FBRUgsUUFBUSxDQUFDLGFBQWEsQ0FBQyxRQUFRLENBQUMsQ0FBQztBQUNqQyxnQkFBZ0IsQ0FBQyxhQUFhLENBQUMsUUFBUSxDQUFDLENBQUM7QUFDekMsZUFBZSxDQUFDLGFBQWEsQ0FBQyxRQUFRLENBQUMsQ0FBQztBQUN4QyxRQUFRLENBQUMsYUFBYSxDQUFDLFFBQVEsQ0FBQyxDQUFDO0FBQ2pDLFFBQVEsQ0FBQyxhQUFhLENBQUMsUUFBUSxDQUFDLENBQUM7QUFDakMsUUFBUSxDQUFDLGFBQWEsQ0FBQyxnQkFBZ0IsQ0FBQyxDQUFDO0FBQ3pDLFFBQVEsQ0FBQyxhQUFhLENBQUMsZUFBZSxDQUFDLENBQUM7QUFFeEMsTUFBTSxpQkFBaUIsR0FBRyxJQUFJLHVDQUFpQixDQUFDLEdBQUcsRUFBRSxtQkFBbUIsRUFBRTtJQUN4RSxHQUFHO0lBQ0gsT0FBTyxFQUFFLFFBQVEsQ0FBQyxPQUFPO0lBQ3pCLFVBQVUsRUFBRSxRQUFRLENBQUMsVUFBVTtJQUMvQixhQUFhLEVBQUUsUUFBUSxDQUFDLFVBQVU7SUFDbEMsYUFBYSxFQUFFLFFBQVEsQ0FBQyxhQUFhO0lBQ3JDLGdCQUFnQixFQUFFLFFBQVEsQ0FBQyxnQkFBZ0I7Q0FDNUMsQ0FBQyxDQUFDO0FBQ0gsaUJBQWlCLENBQUMsYUFBYSxDQUFDLFFBQVEsQ0FBQyxDQUFDO0FBQzFDLGlCQUFpQixDQUFDLGFBQWEsQ0FBQyxRQUFRLENBQUMsQ0FBQyIsInNvdXJjZXNDb250ZW50IjpbIiMhL3Vzci9iaW4vZW52IG5vZGVcbmltcG9ydCAqIGFzIGNkayBmcm9tICdhd3MtY2RrLWxpYic7XG5pbXBvcnQgeyBWcGNTdGFjayB9IGZyb20gJy4uL2xpYi92cGMtc3RhY2snO1xuaW1wb3J0IHsgUmRzU3RhY2sgfSBmcm9tICcuLi9saWIvcmRzLXN0YWNrJztcbmltcG9ydCB7IEVsYXN0aUNhY2hlU3RhY2sgfSBmcm9tICcuLi9saWIvZWxhc3RpY2FjaGUtc3RhY2snO1xuaW1wb3J0IHsgT3BlblNlYXJjaFN0YWNrIH0gZnJvbSAnLi4vbGliL29wZW5zZWFyY2gtc3RhY2snO1xuaW1wb3J0IHsgRWNyU3RhY2sgfSBmcm9tICcuLi9saWIvZWNyLXN0YWNrJztcbmltcG9ydCB7IEVjc1N0YWNrIH0gZnJvbSAnLi4vbGliL2Vjcy1zdGFjayc7XG5pbXBvcnQgeyBQaXBlbGluZVJvbGVTdGFjayB9IGZyb20gJy4uL2xpYi9waXBlbGluZS1yb2xlLXN0YWNrJztcblxuY29uc3QgYXBwID0gbmV3IGNkay5BcHAoKTtcblxuY29uc3QgZW52ID0ge1xuICBhY2NvdW50OiBwcm9jZXNzLmVudi5DREtfREVGQVVMVF9BQ0NPVU5ULFxuICByZWdpb246ICdhcC1zb3V0aC0xJyxcbn07XG5cbmNvbnN0IHZwY1N0YWNrID0gbmV3IFZwY1N0YWNrKGFwcCwgJ1ZwY1N0YWNrJywgeyBlbnYgfSk7XG5cbmNvbnN0IHJkc1N0YWNrID0gbmV3IFJkc1N0YWNrKGFwcCwgJ1Jkc1N0YWNrJywge1xuICBlbnYsXG4gIHZwYzogdnBjU3RhY2sudnBjLFxuICByZHNTZzogdnBjU3RhY2sucmRzU2csXG59KTtcblxuY29uc3QgZWxhc3RpY2FjaGVTdGFjayA9IG5ldyBFbGFzdGlDYWNoZVN0YWNrKGFwcCwgJ0VsYXN0aUNhY2hlU3RhY2snLCB7XG4gIGVudixcbiAgdnBjOiB2cGNTdGFjay52cGMsXG59KTtcblxuY29uc3Qgb3BlblNlYXJjaFN0YWNrID0gbmV3IE9wZW5TZWFyY2hTdGFjayhhcHAsICdPcGVuU2VhcmNoU3RhY2snLCB7XG4gIGVudixcbiAgdnBjOiB2cGNTdGFjay52cGMsXG59KTtcblxuY29uc3QgZWNyU3RhY2sgPSBuZXcgRWNyU3RhY2soYXBwLCAnRWNyU3RhY2snLCB7IGVudiB9KTtcblxuY29uc3QgZWNzU3RhY2sgPSBuZXcgRWNzU3RhY2soYXBwLCAnRWNzU3RhY2snLCB7XG4gIGVudixcbiAgdnBjOiB2cGNTdGFjay52cGMsXG4gIGFwaVJlcG86IGVjclN0YWNrLmFwaVJlcG8sXG4gIHdvcmtlclJlcG86IGVjclN0YWNrLndvcmtlclJlcG8sXG4gIGRhdGFiYXNlU2VjcmV0OiByZHNTdGFjay5kYXRhYmFzZVNlY3JldCxcbiAgZGF0YWJhc2VFbmRwb2ludDogcmRzU3RhY2suZGF0YWJhc2VFbmRwb2ludCxcbiAgcmVkaXNFbmRwb2ludDogZWxhc3RpY2FjaGVTdGFjay5wcmltYXJ5RW5kcG9pbnQsXG4gIG9wZW5TZWFyY2hFbmRwb2ludDogb3BlblNlYXJjaFN0YWNrLmNvbGxlY3Rpb25FbmRwb2ludCxcbiAgcmRzU2c6IHZwY1N0YWNrLnJkc1NnLFxuICByZWRpc1NnOiBlbGFzdGljYWNoZVN0YWNrLnJlZGlzU2csXG59KTtcblxucmRzU3RhY2suYWRkRGVwZW5kZW5jeSh2cGNTdGFjayk7XG5lbGFzdGljYWNoZVN0YWNrLmFkZERlcGVuZGVuY3kodnBjU3RhY2spO1xub3BlblNlYXJjaFN0YWNrLmFkZERlcGVuZGVuY3kodnBjU3RhY2spO1xuZWNzU3RhY2suYWRkRGVwZW5kZW5jeShlY3JTdGFjayk7XG5lY3NTdGFjay5hZGREZXBlbmRlbmN5KHJkc1N0YWNrKTtcbmVjc1N0YWNrLmFkZERlcGVuZGVuY3koZWxhc3RpY2FjaGVTdGFjayk7XG5lY3NTdGFjay5hZGREZXBlbmRlbmN5KG9wZW5TZWFyY2hTdGFjayk7XG5cbmNvbnN0IHBpcGVsaW5lUm9sZVN0YWNrID0gbmV3IFBpcGVsaW5lUm9sZVN0YWNrKGFwcCwgJ1BpcGVsaW5lUm9sZVN0YWNrJywge1xuICBlbnYsXG4gIGFwaVJlcG86IGVjclN0YWNrLmFwaVJlcG8sXG4gIHdvcmtlclJlcG86IGVjclN0YWNrLndvcmtlclJlcG8sXG4gIGVjc0NsdXN0ZXJBcm46IGVjc1N0YWNrLmNsdXN0ZXJBcm4sXG4gIGFwaVNlcnZpY2VBcm46IGVjc1N0YWNrLmFwaVNlcnZpY2VBcm4sXG4gIHdvcmtlclNlcnZpY2VBcm46IGVjc1N0YWNrLndvcmtlclNlcnZpY2VBcm4sXG59KTtcbnBpcGVsaW5lUm9sZVN0YWNrLmFkZERlcGVuZGVuY3koZWNyU3RhY2spO1xucGlwZWxpbmVSb2xlU3RhY2suYWRkRGVwZW5kZW5jeShlY3NTdGFjayk7XG4iXX0=