using TrustPay.Auth.Domain.Entities;

namespace TrustPay.Auth.Application.Models
{
    public sealed class AuthenticationResult
    {
        public User User { get; }
        public string AccessToken { get; }
        public string RefreshToken { get; }

        public AuthenticationResult(User user, string accessToken, string refreshToken)
        {
            User = user;
            AccessToken = accessToken;
            RefreshToken = refreshToken;
        }
    }
}
