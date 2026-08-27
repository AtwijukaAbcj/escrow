using Microsoft.AspNetCore.Mvc;
using System.Threading.Tasks;
using TrustPay.Auth.Application.Interfaces;
using TrustPay.Auth.Api.Models;

namespace TrustPay.Auth.Api.Controllers
{
    [ApiController]
    [Route("api/v1/auth")]
    public class AuthController : ControllerBase
    {
        private readonly IAuthenticationService _authenticationService;

        public AuthController(IAuthenticationService authenticationService)
        {
            _authenticationService = authenticationService;
        }

        [HttpPost("register")]
        public async Task<IActionResult> Register(RegisterRequest request)
        {
            var user = await _authenticationService.RegisterAsync(request.Email, request.Password);
            return CreatedAtAction(nameof(Register), new { userId = user.Id }, new { user.Id, Email = user.Email.Value });
        }

        [HttpPost("login")]
        public async Task<IActionResult> Login(LoginRequest request)
        {
            var result = await _authenticationService.AuthenticateAsync(request.Email, request.Password);
            return Ok(new AuthenticationResponse
            {
                UserId = result.User.Id.Value.ToString(),
                Email = result.User.Email.Value,
                AccessToken = result.AccessToken,
                RefreshToken = result.RefreshToken
            });
        }

        [HttpPost("refresh")]
        public async Task<IActionResult> Refresh(RefreshRequest request)
        {
            var result = await _authenticationService.RefreshTokenAsync(request.RefreshToken);
            return Ok(new AuthenticationResponse
            {
                UserId = result.User.Id.Value.ToString(),
                Email = result.User.Email.Value,
                AccessToken = result.AccessToken,
                RefreshToken = result.RefreshToken
            });
        }

        [HttpPost("logout")]
        public async Task<IActionResult> Logout(RefreshRequest request)
        {
            await _authenticationService.RevokeRefreshTokenAsync(request.RefreshToken);
            return NoContent();
        }
    }
}
