using System.Data.Common;

namespace DemoShop.Data;

public interface IDbConnectionFactory
{
    DbConnection Open();
}

/// <summary>The demo never connects to a database; this factory only exists so the code compiles.</summary>
public sealed class UnconfiguredConnectionFactory : IDbConnectionFactory
{
    public DbConnection Open() =>
        throw new InvalidOperationException("DemoShop has no database configured.");
}
