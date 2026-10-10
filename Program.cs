using Book_Finder.Application.Bestsellers;
using Book_Finder.Infrastructure.Caching;
using Book_Finder.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Caching.Memory;
using Pgvector.EntityFrameworkCore;

var builder = WebApplication.CreateBuilder(args);

// Add services to the container.
builder.Services.AddControllersWithViews();

var connectionString = builder.Configuration.GetConnectionString("DefaultConnection")
    ?? throw new InvalidOperationException("缺少 ConnectionStrings:DefaultConnection 資料庫連線設定");
builder.Services.AddDbContext<AppDbContext>(options =>
    options.UseNpgsql(connectionString, postgres => postgres.UseVector()));

// Bestseller read: EF Core reader wrapped by a process-local cache (ADR-005).
builder.Services.AddMemoryCache();
builder.Services.AddScoped<EfBestsellerReader>();
builder.Services.AddScoped<IBestsellerReader>(provider => new CachedBestsellerReader(
    provider.GetRequiredService<EfBestsellerReader>(),
    provider.GetRequiredService<IMemoryCache>()));
builder.Services.AddScoped<BestsellerService>();

var app = builder.Build();

// Configure the HTTP request pipeline.
if (!app.Environment.IsDevelopment())
{
    app.UseExceptionHandler("/Home/Error");
    // The default HSTS value is 30 days. You may want to change this for production scenarios, see https://aka.ms/aspnetcore-hsts.
    app.UseHsts();
}

app.UseHttpsRedirection();
app.UseRouting();

app.UseAuthorization();

app.MapStaticAssets();

app.MapControllerRoute(
    name: "default",
    pattern: "{controller=Home}/{action=Index}/{id?}")
    .WithStaticAssets();


app.Run();

// Exposes the entry point to tests/WebIntegration (WebApplicationFactory<Program>).
public partial class Program { }
