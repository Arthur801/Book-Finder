using Book_Finder.Application.Bestsellers;
using Book_Finder.Application.Catalog;
using Book_Finder.Application.Library;
using Book_Finder.Application.Recommendation;
using Book_Finder.Infrastructure.BackgroundJobs;
using Book_Finder.Infrastructure.Caching;
using Book_Finder.Infrastructure.Hosting;
using Book_Finder.Infrastructure.Identity;
using Book_Finder.Infrastructure.OpenAi;
using Book_Finder.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Caching.Memory;
using Pgvector.EntityFrameworkCore;

var builder = WebApplication.CreateBuilder(args);

// Add services to the container.
builder.Services.AddControllersWithViews();
builder.Services.AddBookFinderAuth(builder.Configuration);
// Keys are persisted only when DataProtection:KeysPath is set (container deployment; deployment.md §3).
builder.Services.AddBookFinderDataProtection(builder.Configuration);

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

// Book detail read: EF Core reader wrapped by a per-Book cache, 10 minutes (book-catalog.md §5).
builder.Services.AddScoped<EfBookDetailReader>();
builder.Services.AddScoped<IBookDetailReader>(provider => new CachedBookDetailReader(
    provider.GetRequiredService<EfBookDetailReader>(),
    provider.GetRequiredService<IMemoryCache>()));

// General search: local database only, never Google Books (book-catalog.md §3).
builder.Services.AddScoped<IBookSearch, EfBookSearch>();
builder.Services.AddScoped<BookSearchService>();

// 書庫 (Catalog browse): paged list and random home sample, local database only. Bestseller registrations above stay as they are.
builder.Services.AddScoped<IBookBrowse, EfBookBrowse>();
builder.Services.AddScoped<BookBrowseService>();

// AI recommendation: one Recommendation Search per request, EF candidate search and store (recommendation.md §3).
builder.Services.AddScoped<ICandidateSearch, EfCandidateSearch>();
builder.Services.AddScoped<IRecommendationStore, EfRecommendationStore>();
builder.Services.AddScoped<IRecommendationUsage, EfRecommendationUsage>();
// AI search history (#16): read-only port for the user's own saved searches (recommendation.md §12).
builder.Services.AddScoped<IRecommendationHistory, EfRecommendationHistory>();
// AI profile (#18): difficulty reads and stale checks over book_ai_profiles (recommendation.md §9).
builder.Services.AddScoped<IBookProfileStore, EfBookProfileStore>();
builder.Services.AddScoped<RecommendationService>();

// Library (#11): one Library service over the EF store (user-library.md §2).
builder.Services.AddScoped<ILibraryStore, EfLibraryStore>();
builder.Services.AddScoped<LibraryService>();

// Embedding backfill: OpenAI generator + EF store, one round at startup and then every Embedding:Interval (recommendation.md §10).
builder.Services.AddBookFinderOpenAi(builder.Configuration);
builder.Services.AddScoped<IEmbeddingStore, EfEmbeddingStore>();
builder.Services.AddScoped<EmbeddingBackfillService>();
builder.Services.AddHostedService<EmbeddingBackfillWorker>();

// Book AI profile (#18): difficulty reader, scheduler, in-process queue and the worker that drains it (recommendation.md §9).
builder.Services.AddBookProfiles(builder.Configuration);

var app = builder.Build();

// nginx forwards requests from loopback (systemd) or the Docker network (container). Loopback stays trusted;
// ForwardedHeaders:KnownNetworks adds the container network.
app.UseForwardedHeaders(HostingSetup.CreateForwardedHeadersOptions(app.Configuration));

// Configure the HTTP request pipeline.
if (!app.Environment.IsDevelopment())
{
    app.UseExceptionHandler("/Home/Error");
    // The default HSTS value is 30 days. You may want to change this for production scenarios, see https://aka.ms/aspnetcore-hsts.
    app.UseHsts();
}

app.UseHttpsRedirection();
app.UseRouting();

app.UseAuthentication();
app.UseAuthorization();

app.MapStaticAssets();

app.MapControllerRoute(
    name: "default",
    pattern: "{controller=Home}/{action=Index}/{id?}")
    .WithStaticAssets();


app.Run();

// Exposes the entry point to tests/WebIntegration (WebApplicationFactory<Program>).
public partial class Program { }
