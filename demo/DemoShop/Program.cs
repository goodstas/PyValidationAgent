using DemoShop.Data;
using DemoShop.Services;

var builder = WebApplication.CreateBuilder(args);

builder.Services.AddControllers();
builder.Services.AddSingleton<IDbConnectionFactory, UnconfiguredConnectionFactory>();
builder.Services.AddSingleton<ICustomerRepository, InMemoryCustomerRepository>();
builder.Services.AddSingleton<INotificationSender, LoggingNotificationSender>();
builder.Services.AddSingleton<IJobLauncher, QueuedJobLauncher>();
builder.Services.AddScoped<OrderSummaryService>();
builder.Services.AddScoped<NotificationService>();
builder.Services.AddSingleton<ReportCache>();
builder.Services.AddSingleton<SessionStore>();
builder.Services.AddSingleton<TokenService>();
builder.Services.AddSingleton<LegacyHasher>();
builder.Services.AddSingleton<BannerColorPicker>();

var app = builder.Build();

app.MapControllers();
app.MapGet("/reports/{key}", (string key, ReportCache cache) => cache.GetOrAdd(key));
app.MapGet("/banner", (BannerColorPicker picker) => picker.NextColor());

app.Run();
