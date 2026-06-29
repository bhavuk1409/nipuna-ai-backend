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
exports.ElastiCacheStack = void 0;
const cdk = __importStar(require("aws-cdk-lib"));
const ec2 = __importStar(require("aws-cdk-lib/aws-ec2"));
const elasticache = __importStar(require("aws-cdk-lib/aws-elasticache"));
class ElastiCacheStack extends cdk.Stack {
    primaryEndpoint;
    redisSg;
    constructor(scope, id, props) {
        super(scope, id, props);
        const isProd = this.node.tryGetContext('isProd');
        const sg = new ec2.SecurityGroup(this, 'RedisSecurityGroup', {
            vpc: props.vpc,
            allowAllOutbound: true,
        });
        this.redisSg = sg;
        const subnetGroup = new elasticache.CfnSubnetGroup(this, 'RedisSubnetGroup', {
            description: 'Subnet group for ElastiCache Redis',
            subnetIds: props.vpc.isolatedSubnets.map(s => s.subnetId),
        });
        const cluster = new elasticache.CfnCacheCluster(this, 'NipunaRedis', {
            cacheNodeType: isProd ? 'cache.r6g.large' : 'cache.t3.micro',
            engine: 'redis',
            engineVersion: '7.0',
            numCacheNodes: 1,
            vpcSecurityGroupIds: [sg.securityGroupId],
            cacheSubnetGroupName: subnetGroup.ref,
            autoMinorVersionUpgrade: true,
        });
        cluster.addDependency(subnetGroup);
        this.primaryEndpoint = cluster.attrRedisEndpointAddress;
        new cdk.CfnOutput(this, 'RedisEndpoint', {
            value: this.primaryEndpoint,
        });
    }
}
exports.ElastiCacheStack = ElastiCacheStack;
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoiZWxhc3RpY2FjaGUtc3RhY2suanMiLCJzb3VyY2VSb290IjoiIiwic291cmNlcyI6WyJlbGFzdGljYWNoZS1zdGFjay50cyJdLCJuYW1lcyI6W10sIm1hcHBpbmdzIjoiOzs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7QUFBQSxpREFBbUM7QUFFbkMseURBQTJDO0FBQzNDLHlFQUEyRDtBQU0zRCxNQUFhLGdCQUFpQixTQUFRLEdBQUcsQ0FBQyxLQUFLO0lBQzdCLGVBQWUsQ0FBUztJQUN4QixPQUFPLENBQW9CO0lBRTNDLFlBQVksS0FBZ0IsRUFBRSxFQUFVLEVBQUUsS0FBNEI7UUFDcEUsS0FBSyxDQUFDLEtBQUssRUFBRSxFQUFFLEVBQUUsS0FBSyxDQUFDLENBQUM7UUFFeEIsTUFBTSxNQUFNLEdBQUcsSUFBSSxDQUFDLElBQUksQ0FBQyxhQUFhLENBQUMsUUFBUSxDQUFDLENBQUM7UUFFakQsTUFBTSxFQUFFLEdBQUcsSUFBSSxHQUFHLENBQUMsYUFBYSxDQUFDLElBQUksRUFBRSxvQkFBb0IsRUFBRTtZQUMzRCxHQUFHLEVBQUUsS0FBSyxDQUFDLEdBQUc7WUFDZCxnQkFBZ0IsRUFBRSxJQUFJO1NBQ3ZCLENBQUMsQ0FBQztRQUVILElBQUksQ0FBQyxPQUFPLEdBQUcsRUFBRSxDQUFDO1FBRWxCLE1BQU0sV0FBVyxHQUFHLElBQUksV0FBVyxDQUFDLGNBQWMsQ0FBQyxJQUFJLEVBQUUsa0JBQWtCLEVBQUU7WUFDM0UsV0FBVyxFQUFFLG9DQUFvQztZQUNqRCxTQUFTLEVBQUUsS0FBSyxDQUFDLEdBQUcsQ0FBQyxlQUFlLENBQUMsR0FBRyxDQUFDLENBQUMsQ0FBQyxFQUFFLENBQUMsQ0FBQyxDQUFDLFFBQVEsQ0FBQztTQUMxRCxDQUFDLENBQUM7UUFFSCxNQUFNLE9BQU8sR0FBRyxJQUFJLFdBQVcsQ0FBQyxlQUFlLENBQUMsSUFBSSxFQUFFLGFBQWEsRUFBRTtZQUNuRSxhQUFhLEVBQUUsTUFBTSxDQUFDLENBQUMsQ0FBQyxpQkFBaUIsQ0FBQyxDQUFDLENBQUMsZ0JBQWdCO1lBQzVELE1BQU0sRUFBRSxPQUFPO1lBQ2YsYUFBYSxFQUFFLEtBQUs7WUFDcEIsYUFBYSxFQUFFLENBQUM7WUFDaEIsbUJBQW1CLEVBQUUsQ0FBQyxFQUFFLENBQUMsZUFBZSxDQUFDO1lBQ3pDLG9CQUFvQixFQUFFLFdBQVcsQ0FBQyxHQUFHO1lBQ3JDLHVCQUF1QixFQUFFLElBQUk7U0FDOUIsQ0FBQyxDQUFDO1FBRUgsT0FBTyxDQUFDLGFBQWEsQ0FBQyxXQUFXLENBQUMsQ0FBQztRQUVuQyxJQUFJLENBQUMsZUFBZSxHQUFHLE9BQU8sQ0FBQyx3QkFBd0IsQ0FBQztRQUV4RCxJQUFJLEdBQUcsQ0FBQyxTQUFTLENBQUMsSUFBSSxFQUFFLGVBQWUsRUFBRTtZQUN2QyxLQUFLLEVBQUUsSUFBSSxDQUFDLGVBQWU7U0FDNUIsQ0FBQyxDQUFDO0lBQ0wsQ0FBQztDQUNGO0FBdkNELDRDQXVDQyIsInNvdXJjZXNDb250ZW50IjpbImltcG9ydCAqIGFzIGNkayBmcm9tICdhd3MtY2RrLWxpYic7XG5pbXBvcnQgeyBDb25zdHJ1Y3QgfSBmcm9tICdjb25zdHJ1Y3RzJztcbmltcG9ydCAqIGFzIGVjMiBmcm9tICdhd3MtY2RrLWxpYi9hd3MtZWMyJztcbmltcG9ydCAqIGFzIGVsYXN0aWNhY2hlIGZyb20gJ2F3cy1jZGstbGliL2F3cy1lbGFzdGljYWNoZSc7XG5cbmludGVyZmFjZSBFbGFzdGlDYWNoZVN0YWNrUHJvcHMgZXh0ZW5kcyBjZGsuU3RhY2tQcm9wcyB7XG4gIHZwYzogZWMyLlZwYztcbn1cblxuZXhwb3J0IGNsYXNzIEVsYXN0aUNhY2hlU3RhY2sgZXh0ZW5kcyBjZGsuU3RhY2sge1xuICBwdWJsaWMgcmVhZG9ubHkgcHJpbWFyeUVuZHBvaW50OiBzdHJpbmc7XG4gIHB1YmxpYyByZWFkb25seSByZWRpc1NnOiBlYzIuU2VjdXJpdHlHcm91cDtcblxuICBjb25zdHJ1Y3RvcihzY29wZTogQ29uc3RydWN0LCBpZDogc3RyaW5nLCBwcm9wczogRWxhc3RpQ2FjaGVTdGFja1Byb3BzKSB7XG4gICAgc3VwZXIoc2NvcGUsIGlkLCBwcm9wcyk7XG5cbiAgICBjb25zdCBpc1Byb2QgPSB0aGlzLm5vZGUudHJ5R2V0Q29udGV4dCgnaXNQcm9kJyk7XG5cbiAgICBjb25zdCBzZyA9IG5ldyBlYzIuU2VjdXJpdHlHcm91cCh0aGlzLCAnUmVkaXNTZWN1cml0eUdyb3VwJywge1xuICAgICAgdnBjOiBwcm9wcy52cGMsXG4gICAgICBhbGxvd0FsbE91dGJvdW5kOiB0cnVlLFxuICAgIH0pO1xuXG4gICAgdGhpcy5yZWRpc1NnID0gc2c7XG5cbiAgICBjb25zdCBzdWJuZXRHcm91cCA9IG5ldyBlbGFzdGljYWNoZS5DZm5TdWJuZXRHcm91cCh0aGlzLCAnUmVkaXNTdWJuZXRHcm91cCcsIHtcbiAgICAgIGRlc2NyaXB0aW9uOiAnU3VibmV0IGdyb3VwIGZvciBFbGFzdGlDYWNoZSBSZWRpcycsXG4gICAgICBzdWJuZXRJZHM6IHByb3BzLnZwYy5pc29sYXRlZFN1Ym5ldHMubWFwKHMgPT4gcy5zdWJuZXRJZCksXG4gICAgfSk7XG5cbiAgICBjb25zdCBjbHVzdGVyID0gbmV3IGVsYXN0aWNhY2hlLkNmbkNhY2hlQ2x1c3Rlcih0aGlzLCAnTmlwdW5hUmVkaXMnLCB7XG4gICAgICBjYWNoZU5vZGVUeXBlOiBpc1Byb2QgPyAnY2FjaGUucjZnLmxhcmdlJyA6ICdjYWNoZS50My5taWNybycsXG4gICAgICBlbmdpbmU6ICdyZWRpcycsXG4gICAgICBlbmdpbmVWZXJzaW9uOiAnNy4wJyxcbiAgICAgIG51bUNhY2hlTm9kZXM6IDEsXG4gICAgICB2cGNTZWN1cml0eUdyb3VwSWRzOiBbc2cuc2VjdXJpdHlHcm91cElkXSxcbiAgICAgIGNhY2hlU3VibmV0R3JvdXBOYW1lOiBzdWJuZXRHcm91cC5yZWYsXG4gICAgICBhdXRvTWlub3JWZXJzaW9uVXBncmFkZTogdHJ1ZSxcbiAgICB9KTtcblxuICAgIGNsdXN0ZXIuYWRkRGVwZW5kZW5jeShzdWJuZXRHcm91cCk7XG5cbiAgICB0aGlzLnByaW1hcnlFbmRwb2ludCA9IGNsdXN0ZXIuYXR0clJlZGlzRW5kcG9pbnRBZGRyZXNzO1xuXG4gICAgbmV3IGNkay5DZm5PdXRwdXQodGhpcywgJ1JlZGlzRW5kcG9pbnQnLCB7XG4gICAgICB2YWx1ZTogdGhpcy5wcmltYXJ5RW5kcG9pbnQsXG4gICAgfSk7XG4gIH1cbn1cbiJdfQ==