# TrustPay Africa Authentication and User Management Module Plan

## Current repository state

- Workspace contains a Node.js / React prototype only.
- No existing ASP.NET Core project or C# code is present.
- .NET SDK is not installed in the environment (`dotnet --version` failed).
- Current backend is a TypeScript Express server with in-memory/file storage.

## Recommended implementation approach

We will add a separate ASP.NET Core solution for the authentication module, leaving the existing frontend/backend prototype untouched.

### Target architecture

- `ASP.NET Core 9 Web API`
- `C#`
- `Entity Framework Core`
- `PostgreSQL`
- `Redis`
- `JWT access tokens` and `refresh tokens`
- `FluentValidation`
- `Serilog`
- `Swagger / OpenAPI`
- `xUnit`
- `FluentAssertions`
- `Testcontainers`
- Clean Architecture with DDD boundaries

### Solution layout

```
escrow/
  auth-module/
    src/
      TrustPay.Auth.Api/
      TrustPay.Auth.Application/
      TrustPay.Auth.Domain/
      TrustPay.Auth.Infrastructure/
      TrustPay.Auth.Common/
    tests/
      TrustPay.Auth.UnitTests/
      TrustPay.Auth.IntegrationTests/
    docker-compose.auth.yml
    README.auth.md
```

## File-by-file implementation plan

### TrustPay.Auth.Domain

- Entities:
  - `UserId`, `OrganisationId`, `SessionId`, `RefreshTokenId`, `VerificationTokenId`, `InvitationId`, `SecurityEventId`, `ApiClientId`
  - `User`
  - `UserProfile`
  - `UserContact`
  - `UserCredential`
  - `RefreshToken`
  - `UserSession`
  - `TrustedDevice`
  - `MfaMethod`
  - `MfaChallenge`
  - `RecoveryCode`
  - `PasswordHistory`
  - `VerificationToken`
  - `Organisation`
  - `OrganisationMembership`
  - `OrganisationInvitation`
  - `SecurityEvent`
  - `AccountStatusHistory`
  - `UserConsent`
  - `ApiClient`
  - `AuditMetadata` / `BaseEntity`
- Value objects:
  - `EmailAddress`
  - `PhoneNumber`
  - `CountryCode`
  - `Locale`
  - `PasswordHash`
  - `DeviceInfo`
  - `TokenHash`
- Domain events:
  - `UserRegistered`
  - `EmailVerified`
  - `PhoneVerified`
  - `UserAuthenticated`
  - `UserLoginFailed`
  - `UserLocked`
  - `PasswordChanged`
  - `PasswordResetRequested`
  - `MfaEnabled`
  - `MfaDisabled`
  - `OrganisationInvitationCreated`
  - `OrganisationInvitationAccepted`
  - `ActiveOrganisationChanged`
  - `SessionRevoked`
  - `UserSuspended`
  - `AccountClosureRequested`

### TrustPay.Auth.Application

- Commands / DTOs / queries
- Interfaces:
  - `IUserRepository`
  - `IOrganisationRepository`
  - `IRefreshTokenRepository`
  - `ISessionRepository`
  - `IUnitOfWork`
  - `IRateLimitService`
  - `IEmailSender`
  - `ISmsSender`
  - `IEventPublisher`
  - `IDateTimeProvider`
  - `IPasswordHasher`
  - `ITotpProvider`
  - `ISecurityEventRepository`
- Services:
  - `IAuthenticationService`
  - `IRegistrationService`
  - `IMfaService`
  - `IUserProfileService`
  - `IOrganisationService`
  - `ISessionService`
  - `IPasswordService`
  - `IRateLimitingService`
- Validators using FluentValidation
- Application exceptions for RFC 7807 ProblemDetails

### TrustPay.Auth.Infrastructure

- EF Core DbContext and entity configurations
- PostgreSQL mappings
- Redis rate limiting and distributed locks
- Refresh token hashing and storage
- SMS provider abstraction:
  - `ISmsSender`
  - `TwilioSmsSender` stub
- Email sender abstraction:
  - `IEmailSender`
  - `SmtpEmailSender` stub
- Outbox integration for domain events
- Serilog request logging and structured security logs

### TrustPay.Auth.Api

- API controllers under `/api/v1`
- Request/response models
- API pipeline:
  - authentication middleware
  - authorization middleware
  - exception handling middleware
  - correlation ID middleware
  - rate limiting middleware
  - request logging
- Swagger documentation and examples
- Health checks for PostgreSQL and Redis

### Tests

- Unit tests for application services and validators
- Integration tests using Testcontainers with PostgreSQL and Redis
- Security-focused negative tests
- Coverage for refresh token reuse, lockout, MFA, invitation, status restrictions

## Migrations

Planned EF Core migrations:

1. `InitialCreate`:
   - Create user and account tables
   - Create profile, contact, credential, session, refresh token, MFA, verification, invitation, organisation, membership, security event, account status history, consent, API client tables
2. `AddTrustedDeviceAndRecoveryCodes`
3. `AddSoftDeleteAndRetentionMetadata`
4. `AddAccountStatusAndLockoutFields`

## Risks and conflicts

- Current workspace is not an ASP.NET Core solution.
- .NET SDK must be installed before project scaffolding, building, and testing.
- The existing Node/React app and new auth module must be kept separate to avoid unrelated changes.
- We must avoid changing current frontend unless needed for token acquisition.
- Local port assignments and proxy setup may be needed if the existing frontend continues to use the Node backend.

## Next stage

1. Create the ASP.NET Core solution file and projects.
2. Add domain entity models and value objects.
3. Add EF Core DbContext and migrations.
4. Add application service interfaces and implementations.
5. Add API controllers and request/response contracts.
6. Add unit tests and integration tests.
7. Validate with `dotnet build`, `dotnet test`, and migrations.

## Immediate dependency

- Must install .NET 9 SDK in the environment before implementation can proceed.
- PostgreSQL and Redis are required for integration testing; we can use Docker/Testcontainers.

