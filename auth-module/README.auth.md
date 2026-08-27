# TrustPay Authentication Module

This directory contains the ASP.NET Core authentication and user management module for TrustPay Africa.

## Scope

- Authentication API using ASP.NET Core 9
- Clean Architecture with Domain, Application, Infrastructure, and API layers
- PostgreSQL-backed persistence
- JWT-based authentication with refresh token support to be added
- Unit tests using xUnit and FluentAssertions

## Projects

- `TrustPay.Auth.Api` - ASP.NET Core Web API host
- `TrustPay.Auth.Application` - application services, DTOs, commands, validators
- `TrustPay.Auth.Domain` - domain entities, value objects, domain-specific rules
- `TrustPay.Auth.Infrastructure` - EF Core DbContext, repositories, persistence implementation
- `TrustPay.Auth.Common` - shared abstractions and utilities
- `TrustPay.Auth.UnitTests` - unit tests for application services

## Getting started

1. Install .NET 9 SDK.
2. From `auth-module`, run `dotnet build`.
3. Run the API using `dotnet run --project src/TrustPay.Auth.Api/TrustPay.Auth.Api.csproj`.
4. Open `http://localhost:5000/swagger` after the API starts.

## Deployment

### Linux-friendly deployment script

Use the scripts in `auth-module`:

- `deploy.sh` — publishes, starts the API, and writes logs to `logs/`
- `stop.sh` — stops the running process by PID

Example:

```bash
cd auth-module
chmod +x deploy.sh stop.sh
./deploy.sh
```

### Environment variables

The script loads `.env` if present. Set production values there.

## Local dependencies

A companion Docker Compose file is included for PostgreSQL and Redis:

- `docker-compose.auth.yml`

## Next implementation stage

- Add full user registration and login flows.
- Add refresh token persistence.
- Add email verification and MFA.
- Add integration tests with Docker/Testcontainers.
