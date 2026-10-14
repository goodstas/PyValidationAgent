namespace SecureYourCode.PerformanceAnalyzer.Tests;

public class Perf001Tests
{
    private const string Repo = """
        using System.Collections.Generic;
        using System.Threading.Tasks;
        public record Order(int Id, int CustomerId);
        public record Customer(int Id);
        public interface ICustomerRepository
        {
            Task<Customer?> GetByIdAsync(int id);
            Task<IReadOnlyList<Customer>> GetAllAsync();
        }
        """;

    private static Task<System.Collections.Immutable.ImmutableArray<Microsoft.CodeAnalysis.Diagnostic>> Run(string code) =>
        AnalyzerHarness.RunAsync(new Perf001QueryAmplificationAnalyzer(), Repo, AnalyzerHarness.EfStubs, code);

    [Fact]
    public async Task Positive_RepositoryCallInForeach()
    {
        var d = await Run("""
            using System.Collections.Generic;
            using System.Threading.Tasks;
            public class S
            {
                public async Task Run(IEnumerable<Order> orders, ICustomerRepository customerRepository)
                {
                    foreach (var order in orders)
                    {
                        await customerRepository.GetByIdAsync(order.CustomerId);
                    }
                }
            }
            """);
        var diag = Assert.Single(d);
        Assert.Equal("PERF001", diag.Id);
        Assert.Contains("'GetByIdAsync' is invoked inside a loop", diag.GetMessage());
        Assert.Equal(9, AnalyzerHarness.Line(diag));
    }

    [Fact]
    public async Task Positive_SaveChangesAsyncInForLoop_AndNestedConditional()
    {
        var d = await Run("""
            using System.Threading.Tasks;
            using Microsoft.EntityFrameworkCore;
            public class S
            {
                public async Task Run(DbContext dbContext, int n)
                {
                    for (var i = 0; i < n; i++)
                    {
                        if (i % 2 == 0)
                        {
                            await dbContext.SaveChangesAsync();
                        }
                    }
                }
            }
            """);
        Assert.Equal("PERF001", Assert.Single(d).Id);
    }

    [Fact]
    public async Task Positive_ToListOnIQueryableInWhile_AndEfAsyncInDo()
    {
        var d = await Run("""
            using System.Linq;
            using System.Threading.Tasks;
            using Microsoft.EntityFrameworkCore;
            public class S
            {
                public async Task Run(DbSet<Customer> customers, IQueryable<Order> orders)
                {
                    var i = 0;
                    while (i++ < 3)
                    {
                        var list = orders.Where(o => o.Id > i).ToList();
                    }
                    do
                    {
                        await customers.Where(c => c.Id == i).FirstOrDefaultAsync();
                        await customers.FindAsync(i);
                    } while (i-- > 0);
                }
            }
            """);
        Assert.Equal(new[] { "ToList", "FirstOrDefaultAsync", "FindAsync" },
            d.Select(x => x.GetMessage().Split('\'')[1]).ToArray());
    }

    [Fact]
    public async Task Negative_InMemoryToList_QueryConstruction_PreloadedRepository()
    {
        var d = await Run("""
            using System.Collections.Generic;
            using System.Linq;
            using System.Threading.Tasks;
            public class S
            {
                public async Task Run(ICustomerRepository repository, IEnumerable<Order> orders, IQueryable<Order> query, List<int> ids)
                {
                    var customers = await repository.GetAllAsync();
                    foreach (var order in orders)
                    {
                        System.Console.WriteLine(customers.Count);
                        var inMemory = ids.Where(x => x > order.Id).ToList();
                        query = query.Where(o => o.CustomerId == order.CustomerId);
                    }
                }
            }
            """);
        Assert.Empty(d);
    }

    [Fact]
    public async Task Negative_RepositoryCallOutsideLoop_AndLambdaDeclaredInLoop()
    {
        var d = await Run("""
            using System;
            using System.Collections.Generic;
            using System.Threading.Tasks;
            public class S
            {
                public async Task Run(ICustomerRepository repository, IEnumerable<Order> orders)
                {
                    await repository.GetByIdAsync(1);
                    var callbacks = new List<Func<Task>>();
                    foreach (var order in orders)
                    {
                        callbacks.Add(() => repository.GetByIdAsync(order.CustomerId));
                        async Task Local() => await repository.GetByIdAsync(order.Id);
                    }
                }
            }
            """);
        Assert.Empty(d);
    }

    [Fact]
    public async Task Negative_LoopCollectionExpressionIsNotBody()
    {
        var d = await Run("""
            using System.Threading.Tasks;
            public class S
            {
                public async Task Run(ICustomerRepository repository)
                {
                    foreach (var c in await repository.GetAllAsync())
                    {
                        System.Console.WriteLine(c.Id);
                    }
                }
            }
            """);
        Assert.Empty(d);
    }
}
