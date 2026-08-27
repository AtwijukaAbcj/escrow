using System;
using System.Threading.Tasks;
using FluentAssertions;
using Moq;
using TrustPay.Auth.Application.Interfaces;
using TrustPay.Auth.Application.Models;
using TrustPay.Auth.Application.Services;
using TrustPay.Auth.Common.Interfaces;
using TrustPay.Auth.Domain.Entities;
using TrustPay.Auth.Domain.ValueObjects;
using Xunit;

namespace TrustPay.Auth.UnitTests
{
    public class AuthenticationServiceTests
    {
        [Fact]
        public async Task RegisterAsync_ShouldCreateUser_WhenEmailIsNew()
        {
            var userRepository = new Mock<IUserRepository>();
            userRepository.Setup(x => x.FindByEmailAsync(It.IsAny<EmailAddress>())).ReturnsAsync((User?)null);
            userRepository.Setup(x => x.AddAsync(It.IsAny<User>())).Returns(Task.CompletedTask);

            var passwordHasher = new Mock<IPasswordHasher>();
            passwordHasher.Setup(x => x.Hash(It.IsAny<string>())).Returns("hashed-password");

            var dateTimeProvider = new Mock<IDateTimeProvider>();
            dateTimeProvider.Setup(x => x.UtcNow).Returns(DateTime.UtcNow);

            var refreshTokenRepository = new Mock<IRefreshTokenRepository>();
            var tokenHashProvider = new Mock<ITokenHashProvider>();
            var tokenService = new Mock<ITokenService>();
            tokenService.Setup(x => x.CreateToken(It.IsAny<User>())).Returns("test-token");

            var service = new AuthenticationService(
                userRepository.Object,
                refreshTokenRepository.Object,
                passwordHasher.Object,
                dateTimeProvider.Object,
                tokenService.Object,
                tokenHashProvider.Object);

            var user = await service.RegisterAsync("test@example.com", "Password123!");

            user.Email.Value.Should().Be("test@example.com");
            user.PasswordHash.Should().Be("hashed-password");
            userRepository.Verify(x => x.AddAsync(It.IsAny<User>()), Times.Once);
        }

        [Fact]
        public async Task AuthenticateAsync_ShouldReturnAuthenticationResult_WhenCredentialsAreValid()
        {
            var email = EmailAddress.Create("test@example.com");
            var user = User.Create(email, "stored-hash", DateTime.UtcNow);

            var userRepository = new Mock<IUserRepository>();
            userRepository.Setup(x => x.FindByEmailAsync(email)).ReturnsAsync(user);

            var passwordHasher = new Mock<IPasswordHasher>();
            passwordHasher.Setup(x => x.Verify("Password123!", "stored-hash")).Returns(true);

            var dateTimeProvider = new Mock<IDateTimeProvider>();
            dateTimeProvider.Setup(x => x.UtcNow).Returns(DateTime.UtcNow);

            var refreshTokenRepository = new Mock<IRefreshTokenRepository>();
            refreshTokenRepository.Setup(x => x.AddAsync(It.IsAny<TrustPay.Auth.Domain.Entities.RefreshToken>())).Returns(Task.CompletedTask);

            var tokenHashProvider = new Mock<ITokenHashProvider>();
            tokenHashProvider.Setup(x => x.Hash(It.IsAny<string>())).Returns("refresh-token-hash");

            var tokenService = new Mock<ITokenService>();
            tokenService.Setup(x => x.CreateToken(user)).Returns("jwt-token");

            var service = new AuthenticationService(
                userRepository.Object,
                refreshTokenRepository.Object,
                passwordHasher.Object,
                dateTimeProvider.Object,
                tokenService.Object,
                tokenHashProvider.Object);

            var result = await service.AuthenticateAsync("test@example.com", "Password123!");

            result.Should().NotBeNull();
            result.User.Email.Value.Should().Be("test@example.com");
            result.AccessToken.Should().Be("jwt-token");
            result.RefreshToken.Should().NotBeNullOrWhiteSpace();
        }
    }
}
