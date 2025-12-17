/**
 * Auth Stack - Cognito User Pool for authentication.
 * 
 * This stack creates the Cognito User Pool with email-based sign-in,
 * admin-only user creation, and appropriate password policies.
 * 
 * Exports:
 * - UserPoolId
 * - UserPoolArn
 * - UserPoolClientId
 * - UserPoolClientSecret (reference for Secrets stack)
 */

import * as cdk from 'aws-cdk-lib';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import { Construct } from 'constructs';
import { config, exportNames } from './config';

export class AuthStack extends cdk.Stack {
  /** The Cognito User Pool */
  public readonly userPool: cognito.UserPool;
  
  /** The Cognito User Pool Client */
  public readonly userPoolClient: cognito.UserPoolClient;
  
  /** The Admin group */
  public readonly adminGroup: cognito.CfnUserPoolGroup;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // ========================================================================
    // Task 2.1: Create Cognito User Pool
    // Requirements: 2.1, 2.5, 1.6
    // ========================================================================
    
    this.userPool = new cognito.UserPool(this, 'UserPool', {
      userPoolName: config.cognitoPoolName,
      
      // Email-based sign-in (Requirement 2.1)
      signInAliases: {
        email: true,
        username: false,
      },
      
      // Admin-only user creation (Requirement 2.1)
      selfSignUpEnabled: false,
      
      // Auto-verify email
      autoVerify: {
        email: true,
      },
      
      // Password policy (Requirement 2.5)
      // Minimum 8 characters with uppercase, lowercase, and numbers
      passwordPolicy: {
        minLength: 8,
        requireUppercase: true,
        requireLowercase: true,
        requireDigits: true,
        requireSymbols: false,
        tempPasswordValidity: cdk.Duration.days(7),
      },
      
      // Standard attributes
      standardAttributes: {
        email: {
          required: true,
          mutable: true,
        },
      },
      
      // Account recovery via email
      accountRecovery: cognito.AccountRecovery.EMAIL_ONLY,
      
      // Clean deletion (Requirement 1.6)
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // ========================================================================
    // Task 2.2: Add User Pool Client with authentication flows
    // Requirements: 2.2, 2.3
    // ========================================================================
    
    this.userPoolClient = new cognito.UserPoolClient(this, 'UserPoolClient', {
      userPool: this.userPool,
      userPoolClientName: `${config.appName}-client`,
      
      // Authentication flows (Requirement 2.2)
      authFlows: {
        userPassword: true,  // USER_PASSWORD_AUTH
        userSrp: false,
      },
      
      // Generate client secret for server-side auth (Requirement 2.3)
      generateSecret: true,
      
      // Token validity - 8 hours = 480 minutes (Requirement 2.2)
      accessTokenValidity: cdk.Duration.hours(8),
      idTokenValidity: cdk.Duration.hours(8),
      refreshTokenValidity: cdk.Duration.days(30),
      
      // Prevent user existence errors
      preventUserExistenceErrors: true,
    });

    // ========================================================================
    // Task 2.3: Create Admin group
    // Requirement: 2.4
    // ========================================================================
    
    this.adminGroup = new cognito.CfnUserPoolGroup(this, 'AdminGroup', {
      userPoolId: this.userPool.userPoolId,
      groupName: 'Admin',
      description: 'Administrative access group for managing the chat application',
    });

    // ========================================================================
    // Task 2.4: Add stack outputs and exports
    // Requirement: 2.6
    // ========================================================================
    
    // Export User Pool ID
    new cdk.CfnOutput(this, 'UserPoolId', {
      value: this.userPool.userPoolId,
      description: 'Cognito User Pool ID',
      exportName: exportNames.userPoolId,
    });

    // Export User Pool ARN
    new cdk.CfnOutput(this, 'UserPoolArn', {
      value: this.userPool.userPoolArn,
      description: 'Cognito User Pool ARN',
      exportName: exportNames.userPoolArn,
    });

    // Export User Pool Client ID
    new cdk.CfnOutput(this, 'UserPoolClientId', {
      value: this.userPoolClient.userPoolClientId,
      description: 'Cognito User Pool Client ID',
      exportName: exportNames.userPoolClientId,
    });

    // Note: Client secret is not directly exportable as a CloudFormation output
    // because it's a secret value. The Secrets stack will retrieve it using
    // a custom resource or the client will use the Cognito API to get it.
    // We store a reference to the client for the Secrets stack to use.
  }
}
