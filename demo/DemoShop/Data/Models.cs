namespace DemoShop.Data;

public sealed record Customer(int Id, string Name, string Email);

public sealed record OrderLine(int ProductId, int Quantity);

public sealed record Order(int Id, int CustomerId, IReadOnlyList<OrderLine> Lines);

public sealed record OrderSummary(int OrderId, string CustomerName, int ItemCount);
