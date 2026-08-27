using System.Threading.Tasks;
using Microsoft.EntityFrameworkCore;
using TrustPay.Auth.Application.Interfaces;
using TrustPay.Auth.Domain.Entities;
using TrustPay.Auth.Domain.ValueObjects;
using TrustPay.Auth.Infrastructure.Persistence;

namespace TrustPay.Auth.Infrastructure.Repositories
{
    public class UserRepository : IUserRepository
    {
        private readonly AuthDbContext _dbContext;

        public UserRepository(AuthDbContext dbContext)
        {
            _dbContext = dbContext;
        }

        public Task<User?> FindByEmailAsync(EmailAddress email)
        {
            return _dbContext.Users.FirstOrDefaultAsync(u => u.Email.Value == email.Value);
        }

        public Task<User?> FindByIdAsync(UserId id)
        {
            return _dbContext.Users.FirstOrDefaultAsync(u => u.Id == id);
        }

        public Task AddAsync(User user)
        {
            _dbContext.Users.Add(user);
            return _dbContext.SaveChangesAsync();
        }
    }
}
