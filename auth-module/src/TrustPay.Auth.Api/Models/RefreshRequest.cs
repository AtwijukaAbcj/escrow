namespace TrustPay.Auth.Api.Models
{
    public sealed class RefreshRequest
    {
        public string RefreshToken { get; set; } = string.Empty;
    }
}
