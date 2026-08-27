using System;
using System.Security.Cryptography;
using System.Threading.Tasks;
using TrustPay.Auth.Application.Interfaces;
using TrustPay.Auth.Application.Models;
using TrustPay.Auth.Common.Interfaces;
using TrustPay.Auth.Domain.Entities;
using TrustPay.Auth.Domain.ValueObjects;

namespace TrustPay.Auth.Application.Services
{
    public class AuthenticationService : IAuthenticationService
    {
        private readonly IUserRepository _userRepository;
        private readonly IRefreshTokenRepository _refreshTokenRepository;
        private readonly IPasswordHasher _passwordHasher;
        private readonly IDateTimeProvider _dateTimeProvider;
        private readonly ITokenService _tokenService;
        private readonly ITokenHashProvider _tokenHashProvider;

        public AuthenticationService(
            IUserRepository userRepository,
            IRefreshTokenRepository refreshTokenRepository,
            IPasswordHasher passwordHasher,
            IDateTimeProvider dateTimeProvider,
            ITokenService tokenService,
            ITokenHashProvider tokenHashProvider)
        {
            _userRepository = userRepository;
            _refreshTokenRepository = refreshTokenRepository;
            _passwordHasher = passwordHasher;
            _dateTimeProvider = dateTimeProvider;
            _tokenService = tokenService;
            _tokenHashProvider = tokenHashProvider;
        }

        public async Task<User> RegisterAsync(string email, string password)
        {
            var emailAddress = EmailAddress.Create(email);
            var existingUser = await _userRepository.FindByEmailAsync(emailAddress);
            if (existingUser is not null)
            {
                throw new InvalidOperationException("A user with this email already exists.");
            }

            var passwordHash = _passwordHasher.Hash(password);
            var user = User.Create(emailAddress, passwordHash, _dateTimeProvider.UtcNow);
            await _userRepository.AddAsync(user);
            return user;
        }

        public async Task<AuthenticationResult> AuthenticateAsync(string email, string password)
        {
            var emailAddress = EmailAddress.Create(email);
            var user = await _userRepository.FindByEmailAsync(emailAddress);
            if (user is null)
            {
                throw new InvalidOperationException("Invalid email or password.");
            }

            if (!_passwordHasher.Verify(password, user.PasswordHash))
            {
                throw new InvalidOperationException("Invalid email or password.");
            }

            return await CreateAuthenticationResultAsync(user);
        }

        public async Task<AuthenticationResult> RefreshTokenAsync(string refreshToken)
        {
            var refreshTokenHash = _tokenHashProvider.Hash(refreshToken);
            var storedToken = await _refreshTokenRepository.FindByTokenHashAsync(refreshTokenHash);
            if (storedToken is null || storedToken.ExpiresAtUtc <= _dateTimeProvider.UtcNow)
            {
                throw new InvalidOperationException("Refresh token is invalid or expired.");
            }

            var user = await _userRepository.FindByIdAsync(storedToken.UserId);
            if (user is null)
            {
                throw new InvalidOperationException("User not found for refresh token.");
            }

            storedToken.Revoke();
            await _refreshTokenRepository.SaveChangesAsync();
            return await CreateAuthenticationResultAsync(user);
        }

        public async Task RevokeRefreshTokenAsync(string refreshToken)
        {
            var refreshTokenHash = _tokenHashProvider.Hash(refreshToken);
            var storedToken = await _refreshTokenRepository.FindByTokenHashAsync(refreshTokenHash);
            if (storedToken is not null)
            {
                storedToken.Revoke();
                await _refreshTokenRepository.SaveChangesAsync();
            }
        }

        private async Task<AuthenticationResult> CreateAuthenticationResultAsync(User user)
        {
            var accessToken = _tokenService.CreateToken(user);
            var refreshToken = GenerateRefreshToken();
            var refreshTokenHash = _tokenHashProvider.Hash(refreshToken);
            var refreshTokenEntity = RefreshToken.Create(user.Id, refreshTokenHash, _dateTimeProvider.UtcNow.AddDays(30));
            await _refreshTokenRepository.AddAsync(refreshTokenEntity);
            return new AuthenticationResult(user, accessToken, refreshToken);
        }

        private static string GenerateRefreshToken()
        {
            var bytes = RandomNumberGenerator.GetBytes(64);
            return Convert.ToBase64String(bytes);
        }
    }
}
