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
exports.RdsStack = void 0;
const cdk = __importStar(require("aws-cdk-lib"));
const rds = __importStar(require("aws-cdk-lib/aws-rds"));
const ec2 = __importStar(require("aws-cdk-lib/aws-ec2"));
class RdsStack extends cdk.Stack {
    databaseSecret;
    databaseEndpoint;
    constructor(scope, id, props) {
        super(scope, id, props);
        const isProd = this.node.tryGetContext('isProd');
        const db = new rds.DatabaseInstance(this, 'NipunaPostgres', {
            engine: rds.DatabaseInstanceEngine.postgres({
                version: rds.PostgresEngineVersion.VER_15,
            }),
            instanceType: isProd
                ? ec2.InstanceType.of(ec2.InstanceClass.R6G, ec2.InstanceSize.LARGE)
                : ec2.InstanceType.of(ec2.InstanceClass.T3, ec2.InstanceSize.MEDIUM),
            vpc: props.vpc,
            vpcSubnets: {
                subnetType: ec2.SubnetType.PRIVATE_ISOLATED,
            },
            securityGroups: [props.rdsSg],
            allocatedStorage: 20,
            maxAllocatedStorage: 100,
            multiAz: isProd,
            deletionProtection: isProd,
            databaseName: 'nipunadb',
            credentials: rds.Credentials.fromGeneratedSecret('postgres'),
            backupRetention: cdk.Duration.days(7),
            removalPolicy: isProd
                ? cdk.RemovalPolicy.RETAIN
                : cdk.RemovalPolicy.DESTROY,
        });
        this.databaseSecret = db.secret;
        this.databaseEndpoint = db.dbInstanceEndpointAddress;
        new cdk.CfnOutput(this, 'DatabaseEndpoint', {
            value: db.dbInstanceEndpointAddress,
        });
        new cdk.CfnOutput(this, 'DatabaseSecretArn', {
            value: db.secret.secretArn,
        });
    }
}
exports.RdsStack = RdsStack;
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoicmRzLXN0YWNrLmpzIiwic291cmNlUm9vdCI6IiIsInNvdXJjZXMiOlsicmRzLXN0YWNrLnRzIl0sIm5hbWVzIjpbXSwibWFwcGluZ3MiOiI7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7OztBQUFBLGlEQUFtQztBQUVuQyx5REFBMkM7QUFDM0MseURBQTJDO0FBTzNDLE1BQWEsUUFBUyxTQUFRLEdBQUcsQ0FBQyxLQUFLO0lBQ3JCLGNBQWMsQ0FBaUM7SUFDL0MsZ0JBQWdCLENBQVM7SUFFekMsWUFBWSxLQUFnQixFQUFFLEVBQVUsRUFBRSxLQUFvQjtRQUM1RCxLQUFLLENBQUMsS0FBSyxFQUFFLEVBQUUsRUFBRSxLQUFLLENBQUMsQ0FBQztRQUV4QixNQUFNLE1BQU0sR0FBRyxJQUFJLENBQUMsSUFBSSxDQUFDLGFBQWEsQ0FBQyxRQUFRLENBQUMsQ0FBQztRQUVqRCxNQUFNLEVBQUUsR0FBRyxJQUFJLEdBQUcsQ0FBQyxnQkFBZ0IsQ0FBQyxJQUFJLEVBQUUsZ0JBQWdCLEVBQUU7WUFDMUQsTUFBTSxFQUFFLEdBQUcsQ0FBQyxzQkFBc0IsQ0FBQyxRQUFRLENBQUM7Z0JBQzFDLE9BQU8sRUFBRSxHQUFHLENBQUMscUJBQXFCLENBQUMsTUFBTTthQUMxQyxDQUFDO1lBRUYsWUFBWSxFQUFFLE1BQU07Z0JBQ2xCLENBQUMsQ0FBQyxHQUFHLENBQUMsWUFBWSxDQUFDLEVBQUUsQ0FDakIsR0FBRyxDQUFDLGFBQWEsQ0FBQyxHQUFHLEVBQ3JCLEdBQUcsQ0FBQyxZQUFZLENBQUMsS0FBSyxDQUN2QjtnQkFDSCxDQUFDLENBQUMsR0FBRyxDQUFDLFlBQVksQ0FBQyxFQUFFLENBQ2pCLEdBQUcsQ0FBQyxhQUFhLENBQUMsRUFBRSxFQUNwQixHQUFHLENBQUMsWUFBWSxDQUFDLE1BQU0sQ0FDeEI7WUFFTCxHQUFHLEVBQUUsS0FBSyxDQUFDLEdBQUc7WUFFZCxVQUFVLEVBQUU7Z0JBQ1YsVUFBVSxFQUFFLEdBQUcsQ0FBQyxVQUFVLENBQUMsZ0JBQWdCO2FBQzVDO1lBRUQsY0FBYyxFQUFFLENBQUMsS0FBSyxDQUFDLEtBQUssQ0FBQztZQUU3QixnQkFBZ0IsRUFBRSxFQUFFO1lBQ3BCLG1CQUFtQixFQUFFLEdBQUc7WUFFeEIsT0FBTyxFQUFFLE1BQU07WUFFZixrQkFBa0IsRUFBRSxNQUFNO1lBRTFCLFlBQVksRUFBRSxVQUFVO1lBRXhCLFdBQVcsRUFBRSxHQUFHLENBQUMsV0FBVyxDQUFDLG1CQUFtQixDQUFDLFVBQVUsQ0FBQztZQUU1RCxlQUFlLEVBQUUsR0FBRyxDQUFDLFFBQVEsQ0FBQyxJQUFJLENBQUMsQ0FBQyxDQUFDO1lBRXJDLGFBQWEsRUFBRSxNQUFNO2dCQUNuQixDQUFDLENBQUMsR0FBRyxDQUFDLGFBQWEsQ0FBQyxNQUFNO2dCQUMxQixDQUFDLENBQUMsR0FBRyxDQUFDLGFBQWEsQ0FBQyxPQUFPO1NBQzlCLENBQUMsQ0FBQztRQUVILElBQUksQ0FBQyxjQUFjLEdBQUcsRUFBRSxDQUFDLE1BQU8sQ0FBQztRQUNqQyxJQUFJLENBQUMsZ0JBQWdCLEdBQUcsRUFBRSxDQUFDLHlCQUF5QixDQUFDO1FBRXJELElBQUksR0FBRyxDQUFDLFNBQVMsQ0FBQyxJQUFJLEVBQUUsa0JBQWtCLEVBQUU7WUFDMUMsS0FBSyxFQUFFLEVBQUUsQ0FBQyx5QkFBeUI7U0FDcEMsQ0FBQyxDQUFDO1FBRUgsSUFBSSxHQUFHLENBQUMsU0FBUyxDQUFDLElBQUksRUFBRSxtQkFBbUIsRUFBRTtZQUMzQyxLQUFLLEVBQUUsRUFBRSxDQUFDLE1BQU8sQ0FBQyxTQUFTO1NBQzVCLENBQUMsQ0FBQztJQUNMLENBQUM7Q0FDRjtBQTdERCw0QkE2REMiLCJzb3VyY2VzQ29udGVudCI6WyJpbXBvcnQgKiBhcyBjZGsgZnJvbSAnYXdzLWNkay1saWInO1xuaW1wb3J0IHsgQ29uc3RydWN0IH0gZnJvbSAnY29uc3RydWN0cyc7XG5pbXBvcnQgKiBhcyByZHMgZnJvbSAnYXdzLWNkay1saWIvYXdzLXJkcyc7XG5pbXBvcnQgKiBhcyBlYzIgZnJvbSAnYXdzLWNkay1saWIvYXdzLWVjMic7XG5cbmludGVyZmFjZSBSZHNTdGFja1Byb3BzIGV4dGVuZHMgY2RrLlN0YWNrUHJvcHMge1xuICB2cGM6IGVjMi5WcGM7XG4gIHJkc1NnOiBlYzIuU2VjdXJpdHlHcm91cDtcbn1cblxuZXhwb3J0IGNsYXNzIFJkc1N0YWNrIGV4dGVuZHMgY2RrLlN0YWNrIHtcbiAgcHVibGljIHJlYWRvbmx5IGRhdGFiYXNlU2VjcmV0OiBjZGsuYXdzX3NlY3JldHNtYW5hZ2VyLklTZWNyZXQ7XG4gIHB1YmxpYyByZWFkb25seSBkYXRhYmFzZUVuZHBvaW50OiBzdHJpbmc7XG5cbiAgY29uc3RydWN0b3Ioc2NvcGU6IENvbnN0cnVjdCwgaWQ6IHN0cmluZywgcHJvcHM6IFJkc1N0YWNrUHJvcHMpIHtcbiAgICBzdXBlcihzY29wZSwgaWQsIHByb3BzKTtcblxuICAgIGNvbnN0IGlzUHJvZCA9IHRoaXMubm9kZS50cnlHZXRDb250ZXh0KCdpc1Byb2QnKTtcblxuICAgIGNvbnN0IGRiID0gbmV3IHJkcy5EYXRhYmFzZUluc3RhbmNlKHRoaXMsICdOaXB1bmFQb3N0Z3JlcycsIHtcbiAgICAgIGVuZ2luZTogcmRzLkRhdGFiYXNlSW5zdGFuY2VFbmdpbmUucG9zdGdyZXMoe1xuICAgICAgICB2ZXJzaW9uOiByZHMuUG9zdGdyZXNFbmdpbmVWZXJzaW9uLlZFUl8xNSxcbiAgICAgIH0pLFxuXG4gICAgICBpbnN0YW5jZVR5cGU6IGlzUHJvZFxuICAgICAgICA/IGVjMi5JbnN0YW5jZVR5cGUub2YoXG4gICAgICAgICAgICBlYzIuSW5zdGFuY2VDbGFzcy5SNkcsXG4gICAgICAgICAgICBlYzIuSW5zdGFuY2VTaXplLkxBUkdFXG4gICAgICAgICAgKVxuICAgICAgICA6IGVjMi5JbnN0YW5jZVR5cGUub2YoXG4gICAgICAgICAgICBlYzIuSW5zdGFuY2VDbGFzcy5UMyxcbiAgICAgICAgICAgIGVjMi5JbnN0YW5jZVNpemUuTUVESVVNXG4gICAgICAgICAgKSxcblxuICAgICAgdnBjOiBwcm9wcy52cGMsXG5cbiAgICAgIHZwY1N1Ym5ldHM6IHtcbiAgICAgICAgc3VibmV0VHlwZTogZWMyLlN1Ym5ldFR5cGUuUFJJVkFURV9JU09MQVRFRCxcbiAgICAgIH0sXG5cbiAgICAgIHNlY3VyaXR5R3JvdXBzOiBbcHJvcHMucmRzU2ddLFxuXG4gICAgICBhbGxvY2F0ZWRTdG9yYWdlOiAyMCxcbiAgICAgIG1heEFsbG9jYXRlZFN0b3JhZ2U6IDEwMCxcblxuICAgICAgbXVsdGlBejogaXNQcm9kLFxuXG4gICAgICBkZWxldGlvblByb3RlY3Rpb246IGlzUHJvZCxcblxuICAgICAgZGF0YWJhc2VOYW1lOiAnbmlwdW5hZGInLFxuXG4gICAgICBjcmVkZW50aWFsczogcmRzLkNyZWRlbnRpYWxzLmZyb21HZW5lcmF0ZWRTZWNyZXQoJ3Bvc3RncmVzJyksXG5cbiAgICAgIGJhY2t1cFJldGVudGlvbjogY2RrLkR1cmF0aW9uLmRheXMoNyksXG5cbiAgICAgIHJlbW92YWxQb2xpY3k6IGlzUHJvZFxuICAgICAgICA/IGNkay5SZW1vdmFsUG9saWN5LlJFVEFJTlxuICAgICAgICA6IGNkay5SZW1vdmFsUG9saWN5LkRFU1RST1ksXG4gICAgfSk7XG5cbiAgICB0aGlzLmRhdGFiYXNlU2VjcmV0ID0gZGIuc2VjcmV0ITtcbiAgICB0aGlzLmRhdGFiYXNlRW5kcG9pbnQgPSBkYi5kYkluc3RhbmNlRW5kcG9pbnRBZGRyZXNzO1xuXG4gICAgbmV3IGNkay5DZm5PdXRwdXQodGhpcywgJ0RhdGFiYXNlRW5kcG9pbnQnLCB7XG4gICAgICB2YWx1ZTogZGIuZGJJbnN0YW5jZUVuZHBvaW50QWRkcmVzcyxcbiAgICB9KTtcblxuICAgIG5ldyBjZGsuQ2ZuT3V0cHV0KHRoaXMsICdEYXRhYmFzZVNlY3JldEFybicsIHtcbiAgICAgIHZhbHVlOiBkYi5zZWNyZXQhLnNlY3JldEFybixcbiAgICB9KTtcbiAgfVxufSJdfQ==