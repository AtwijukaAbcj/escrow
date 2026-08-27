FROM mcr.microsoft.com/dotnet/aspnet:9.0 AS base
WORKDIR /app

FROM mcr.microsoft.com/dotnet/sdk:9.0 AS build
WORKDIR /src
COPY ["src/TrustPay.Auth.Api/TrustPay.Auth.Api.csproj", "src/TrustPay.Auth.Api/"]
COPY ["src/TrustPay.Auth.Application/TrustPay.Auth.Application.csproj", "src/TrustPay.Auth.Application/"]
COPY ["src/TrustPay.Auth.Domain/TrustPay.Auth.Domain.csproj", "src/TrustPay.Auth.Domain/"]
COPY ["src/TrustPay.Auth.Infrastructure/TrustPay.Auth.Infrastructure.csproj", "src/TrustPay.Auth.Infrastructure/"]
COPY ["src/TrustPay.Auth.Common/TrustPay.Auth.Common.csproj", "src/TrustPay.Auth.Common/"]
RUN dotnet restore "src/TrustPay.Auth.Api/TrustPay.Auth.Api.csproj"

COPY . .
WORKDIR "/src/src/TrustPay.Auth.Api"
RUN dotnet publish "TrustPay.Auth.Api.csproj" -c Release -o /app/publish

FROM base AS final
WORKDIR /app
COPY --from=build /app/publish .
EXPOSE 80
EXPOSE 443
ENTRYPOINT ["dotnet", "TrustPay.Auth.Api.dll"]
