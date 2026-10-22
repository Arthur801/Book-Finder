using Book_Finder.Application.Common;
using Book_Finder.Application.Recommendation;
using Book_Finder.Domain.Entities;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using Microsoft.Extensions.Time.Testing;
using TestDoubles;

namespace UnitTests;

public sealed class RecommendationServiceTests
{
    private const string Requirement = "想找一本關於海洋生物的繁體中文書";
    private const string Retrieval = "海洋生物 科普 入門";
    private static readonly Guid UserId = Guid.Parse("11111111-2222-3333-4444-555555555555");
    private static readonly DateTime SavedAt = new(2026, 10, 21, 4, 0, 0, DateTimeKind.Utc);

    // ----- Happy path and data flow -----

    [Fact]
    public async Task Happy_path_passes_each_step_its_inputs_and_saves_the_validated_results()
    {
        var h = Build();
        var filters = new RequirementFilters("zh", 2015, 2024, null, 400, null, null);
        h.Parser.Respond(Requirement, new ParsedRequirement(filters, Retrieval, []));
        var vector = new float[] { 0.25f, 0.5f };
        h.Embeddings.Respond(Retrieval, vector);
        h.Candidates.Result = [Book("A", 0.9), Book("B", 0.7)];

        var outcome = await Recommend(h, UserId, Requirement, CancellationToken.None);

        Assert.Equal([Requirement], h.Parser.Calls);
        Assert.Equal([Retrieval], h.Embeddings.Calls);

        var search = Assert.Single(h.Candidates.Calls);
        Assert.Equal(filters, search.Filters);
        Assert.Equal(vector, search.QueryVector);
        Assert.Equal(0.45, search.Threshold);
        Assert.Equal(30, search.TopK);

        var ranking = Assert.Single(h.Ranker.Calls);
        Assert.Equal(Requirement, ranking.RequirementText);
        Assert.Equal([1, 2], ranking.Candidates.Select(c => c.CandidateNo));
        Assert.Equal(["A", "B"], ranking.Candidates.Select(c => c.Title));

        var save = Assert.Single(h.Store.Calls);
        Assert.Equal(UserId, save.UserId);
        Assert.Equal(Requirement, save.RequirementText);
        Assert.Equal([1, 2], save.Results.Select(r => (int)r.Rank));
        Assert.Equal(["A", "B"], save.Results.Select(r => r.Book.Title));
        Assert.Equal("理由 1", save.Results[0].Reason);

        Assert.Equal(h.Store.Saved.SearchId, outcome.SearchId);
        Assert.Equal(SavedAt, outcome.CreatedAt);
        Assert.Equal(save.Results, outcome.Results);
    }

    [Fact]
    public async Task Ranker_receives_candidates_with_descriptions_truncated_to_the_configured_length()
    {
        var h = Build(new RecommendationOptions { RankingDescriptionLength = 5 });
        h.Candidates.Result = [Book("A", description: "一二三四五六七八")];

        await Recommend(h, UserId, Requirement, CancellationToken.None);

        var candidate = Assert.Single(Assert.Single(h.Ranker.Calls).Candidates);
        Assert.Equal("一二三四五", candidate.Description);
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("   ")]
    public async Task Blank_retrieval_text_falls_back_to_the_original_requirement_for_embedding(string? retrievalText)
    {
        var h = Build();
        h.Parser.Respond(Requirement, new ParsedRequirement(RequirementFilters.None, retrievalText!, []));

        await Recommend(h, UserId, Requirement, CancellationToken.None);

        Assert.Equal([Requirement], h.Embeddings.Calls);
    }

    [Fact]
    public async Task Options_threshold_and_top_k_reach_the_candidate_search()
    {
        var h = Build(new RecommendationOptions { SimilarityThreshold = 0.25, TopK = 7 });

        await Recommend(h, UserId, Requirement, CancellationToken.None);

        var search = Assert.Single(h.Candidates.Calls);
        Assert.Equal(0.25, search.Threshold);
        Assert.Equal(7, search.TopK);
    }

    [Fact]
    public async Task Result_limit_from_options_caps_the_saved_and_returned_results()
    {
        var h = Build(new RecommendationOptions { ResultLimit = 3 });
        h.Candidates.Result = Enumerable.Range(1, 5).Select(i => Book($"Book {i}")).ToList();

        var outcome = await Recommend(h, UserId, Requirement, CancellationToken.None);

        Assert.Equal([1, 2, 3], outcome.Results.Select(r => (int)r.Rank));
        Assert.Equal(3, Assert.Single(h.Store.Calls).Results.Count);
    }

    // ----- Filters and sanitizing -----

    [Fact]
    public async Task Reversed_years_are_dropped_before_search_and_the_dropped_names_are_logged()
    {
        var h = Build();
        h.Parser.Respond(Requirement, new ParsedRequirement(new RequirementFilters("zh", 2024, 2010, null, null, null, null), Retrieval, []));

        await Recommend(h, UserId, Requirement, CancellationToken.None);

        var search = Assert.Single(h.Candidates.Calls);
        Assert.Equal(new RequirementFilters("zh", null, null, null, null, null, null), search.Filters);

        var warning = Assert.Single(h.Logger.Entries, e => e.Level == LogLevel.Warning);
        Assert.Contains("published_year_from", warning.Message);
        Assert.Contains("published_year_to", warning.Message);
    }

    [Fact]
    public async Task Summary_log_records_the_sanitized_filters_not_the_rejected_ones()
    {
        var h = Build();
        h.Parser.Respond(Requirement, new ParsedRequirement(new RequirementFilters(null, 2024, 2010, 0, null, null, null), Retrieval, []));

        await Recommend(h, UserId, Requirement, CancellationToken.None);

        var summary = Assert.Single(h.Logger.Entries, e => e.Level == LogLevel.Information);
        Assert.Equal(new RequirementFilters(null, null, null, null, null, null, null), summary.Properties["Filters"]);
    }

    // ----- Zero candidates -----

    [Fact]
    public async Task Zero_candidates_skip_the_ranker_and_save_an_empty_search()
    {
        var h = Build();
        h.Candidates.Result = [];

        var outcome = await Recommend(h, UserId, Requirement, CancellationToken.None);

        Assert.Empty(h.Ranker.Calls);
        var save = Assert.Single(h.Store.Calls);
        Assert.Empty(save.Results);
        Assert.Empty(outcome.Results);
        Assert.Equal(h.Store.Saved.SearchId, outcome.SearchId);
    }

    [Fact]
    public async Task Zero_candidates_log_null_similarity_and_zero_ranking_time()
    {
        var h = Build();
        h.Candidates.Result = [];

        await Recommend(h, UserId, Requirement, CancellationToken.None);

        var summary = Assert.Single(h.Logger.Entries, e => e.Level == LogLevel.Information);
        Assert.Equal(0, summary.Properties["CandidateCount"]);
        Assert.Null(summary.Properties["SimilarityMax"]);
        Assert.Null(summary.Properties["SimilarityMin"]);
        Assert.Equal(0d, summary.Properties["RankingMs"]);
    }

    // ----- Ranking validation -----

    [Fact]
    public async Task Non_candidate_number_is_discarded_logged_and_results_are_capped_at_ten()
    {
        var h = Build();
        h.Candidates.Result = Enumerable.Range(1, 12).Select(i => Book($"Book {i}")).ToList();
        // 99 is not a candidate number; 11 and 12 are valid but fall past the limit, so they are cut silently.
        var items = Enumerable.Range(1, 5).Select(Item)
            .Append(new RankedItem(99, 0.5, "理由 99"))
            .Concat(Enumerable.Range(6, 7).Select(Item))
            .ToList();
        h.Ranker.RespondToAll(items);

        var outcome = await Recommend(h, UserId, Requirement, CancellationToken.None);

        Assert.Equal(10, outcome.Results.Count);
        Assert.Equal(Enumerable.Range(1, 10).Select(i => (short)i), outcome.Results.Select(r => r.Rank));
        Assert.Equal(Enumerable.Range(1, 10).Select(i => $"Book {i}"), outcome.Results.Select(r => r.Book.Title));

        var warning = Assert.Single(h.Logger.Entries, e => e.Level == LogLevel.Warning);
        Assert.Contains("99", warning.Message);
        Assert.Equal([99], (IEnumerable<int>)warning.Properties["DiscardedCandidateNos"]!);
    }

    // ----- Failure propagation (REC-09) -----

    [Fact]
    public async Task Parser_failure_propagates_unchanged_and_nothing_is_saved()
    {
        var h = Build();
        var error = new InvalidOperationException("parser down");
        h.Parser.ThrowForAll(error);

        var actual = await Assert.ThrowsAsync<InvalidOperationException>(() => Recommend(h, UserId, Requirement, CancellationToken.None));

        Assert.Same(error, actual);
        AssertNothingSaved(h);
        Assert.Empty(h.Embeddings.Calls);
        Assert.Empty(h.Candidates.Calls);
    }

    [Fact]
    public async Task Embedding_failure_propagates_unchanged_and_nothing_is_saved()
    {
        var h = Build();
        var error = new InvalidOperationException("embedding down");
        h.Embeddings.Throw(Requirement, error);

        var actual = await Assert.ThrowsAsync<InvalidOperationException>(() => Recommend(h, UserId, Requirement, CancellationToken.None));

        Assert.Same(error, actual);
        AssertNothingSaved(h);
        Assert.Empty(h.Candidates.Calls);
    }

    [Fact]
    public async Task Search_failure_propagates_unchanged_and_nothing_is_saved()
    {
        var h = Build();
        var error = new InvalidOperationException("search down");
        h.Candidates.Error = error;

        var actual = await Assert.ThrowsAsync<InvalidOperationException>(() => Recommend(h, UserId, Requirement, CancellationToken.None));

        Assert.Same(error, actual);
        AssertNothingSaved(h);
        Assert.Empty(h.Ranker.Calls);
    }

    [Fact]
    public async Task Ranker_failure_propagates_unchanged_and_nothing_is_saved()
    {
        var h = Build();
        h.Candidates.Result = [Book("A")];
        var error = new InvalidOperationException("ranker down");
        h.Ranker.ThrowForAll(error);

        var actual = await Assert.ThrowsAsync<InvalidOperationException>(() => Recommend(h, UserId, Requirement, CancellationToken.None));

        Assert.Same(error, actual);
        AssertNothingSaved(h);
    }

    [Fact]
    public async Task Store_failure_propagates_unchanged_and_no_summary_is_logged()
    {
        var h = Build();
        h.Candidates.Result = [Book("A")];
        var error = new InvalidOperationException("database down");
        h.Store.Error = error;

        var actual = await Assert.ThrowsAsync<InvalidOperationException>(() => Recommend(h, UserId, Requirement, CancellationToken.None));

        Assert.Same(error, actual);
        Assert.Single(h.Store.Calls);
        Assert.DoesNotContain(h.Logger.Entries, e => e.Level == LogLevel.Information);
    }

    [Fact]
    public async Task Cancellation_propagates_before_the_search_and_nothing_is_saved()
    {
        var h = Build();
        using var cts = new CancellationTokenSource();
        cts.Cancel();

        await Assert.ThrowsAsync<OperationCanceledException>(() => Recommend(h, UserId, Requirement, cts.Token));

        AssertNothingSaved(h);
        Assert.Empty(h.Candidates.Calls);
    }

    // ----- Logging (§14) -----

    [Fact]
    public async Task Summary_is_logged_once_at_information_and_never_contains_the_requirement_text()
    {
        var h = Build();
        const string secret = "SECRET-REQUIREMENT-TEXT-7f3a";
        h.Parser.Respond(secret, new ParsedRequirement(RequirementFilters.None, "SECRET-RETRIEVAL-9b1c", []));
        h.Candidates.Result = [Book("A", 0.9), Book("B", 0.7)];

        var outcome = await Recommend(h, UserId, secret, CancellationToken.None);

        var summary = Assert.Single(h.Logger.Entries, e => e.Level == LogLevel.Information);
        Assert.DoesNotContain("SECRET", summary.Message);
        Assert.DoesNotContain(summary.Properties, p => p.Value is string text && text.Contains("SECRET"));
        Assert.Equal(outcome.SearchId, summary.Properties["SearchId"]);
    }

    [Fact]
    public async Task Summary_carries_the_search_metrics_the_spec_asks_for()
    {
        var h = Build();
        h.Candidates.Result = [Book("A", 0.9), Book("B", 0.7)];

        var outcome = await Recommend(h, UserId, Requirement, CancellationToken.None);

        var summary = Assert.Single(h.Logger.Entries, e => e.Level == LogLevel.Information);
        Assert.Equal(outcome.SearchId, summary.Properties["SearchId"]);
        Assert.Equal(2, summary.Properties["CandidateCount"]);
        Assert.Equal(0.9, summary.Properties["SimilarityMax"]);
        Assert.Equal(0.7, summary.Properties["SimilarityMin"]);
        Assert.Equal(2, summary.Properties["ResultCount"]);
        Assert.Equal(false, summary.Properties["FallbackUsed"]);
        Assert.Equal(0, summary.Properties["GoogleBooksWritten"]);
        Assert.Empty((IEnumerable<int>)summary.Properties["DiscardedCandidateNos"]!);
        foreach (var key in new[] { "ParseMs", "EmbeddingMs", "SearchMs", "RankingMs", "SaveMs" })
            Assert.IsType<double>(summary.Properties[key]);
    }

    // ----- Daily limit (§11) -----

    [Fact]
    public async Task Reaching_the_daily_limit_returns_daily_limit_reached_and_calls_no_external_service()
    {
        var h = Build();
        h.Usage.Count = 20;

        var attempt = await h.Service.RecommendAsync(UserId, Requirement, CancellationToken.None);

        Assert.IsType<RecommendationAttempt.DailyLimitReached>(attempt);
        Assert.Empty(h.Parser.Calls);
        Assert.Empty(h.Embeddings.Calls);
        Assert.Empty(h.Candidates.Calls);
        Assert.Empty(h.Ranker.Calls);
        Assert.Empty(h.Store.Calls);
    }

    [Fact]
    public async Task One_search_below_the_daily_limit_runs_the_full_flow()
    {
        var h = Build();
        h.Usage.Count = 19;

        var attempt = await h.Service.RecommendAsync(UserId, Requirement, CancellationToken.None);

        Assert.IsType<RecommendationAttempt.Succeeded>(attempt);
        Assert.Single(h.Parser.Calls);
        Assert.Single(h.Store.Calls);
    }

    [Fact]
    public async Task The_limit_comes_from_options()
    {
        var h = Build(new RecommendationOptions { DailyLimit = 3 });
        h.Usage.Count = 3;

        var attempt = await h.Service.RecommendAsync(UserId, Requirement, CancellationToken.None);

        Assert.IsType<RecommendationAttempt.DailyLimitReached>(attempt);
    }

    [Fact]
    public async Task The_count_covers_the_taipei_day_that_contains_now()
    {
        var h = Build();

        await h.Service.RecommendAsync(UserId, Requirement, CancellationToken.None);

        // SavedAt is 12:00 on 2026-10-21 in Taipei, so the Taipei day started at 00:00 +08:00, which is 16:00 UTC on 2026-10-20.
        var call = Assert.Single(h.Usage.Calls);
        Assert.Equal(UserId, call.UserId);
        Assert.Equal(new DateTime(2026, 10, 20, 16, 0, 0, DateTimeKind.Utc), call.SinceUtc);
        Assert.Equal(TaipeiTimeZone.StartOfDayUtc(new DateTimeOffset(SavedAt)), call.SinceUtc);
    }

    [Fact]
    public async Task The_count_is_taken_before_the_parser_runs()
    {
        var h = Build();

        await h.Service.RecommendAsync(UserId, Requirement, CancellationToken.None);

        Assert.Equal(0, h.Usage.ParserCallsBeforeCount);
    }

    [Fact]
    public async Task Reaching_the_limit_logs_one_information_line_without_the_requirement_text()
    {
        var h = Build();
        h.Usage.Count = 20;
        const string secret = "SECRET-LIMIT-REQUIREMENT-41c2";

        await h.Service.RecommendAsync(UserId, secret, CancellationToken.None);

        var entry = Assert.Single(h.Logger.Entries);
        Assert.Equal(LogLevel.Information, entry.Level);
        Assert.Equal(UserId, entry.Properties["UserId"]);
        Assert.Equal(20, entry.Properties["Used"]);
        Assert.Equal(20, entry.Properties["DailyLimit"]);
        Assert.DoesNotContain("SECRET", entry.Message);
        Assert.DoesNotContain(entry.Properties, p => p.Value is string text && text.Contains("SECRET"));
    }

    // ----- Timeout (§13) -----

    [Fact]
    public async Task Ranker_still_waiting_at_60_seconds_times_out_and_nothing_is_saved()
    {
        var h = Build();
        h.Candidates.Result = [Book("A")];
        h.Ranker.Gate.Close();

        var pending = h.Service.RecommendAsync(UserId, Requirement, CancellationToken.None);
        await h.Ranker.Gate.Entered;
        h.Time.Advance(TimeSpan.FromSeconds(60));

        await Assert.ThrowsAsync<AiTimeoutException>(() => pending);
        AssertNothingSaved(h);
    }

    [Fact]
    public async Task Ranker_still_waiting_at_59_seconds_does_not_time_out_and_finishes_normally()
    {
        var h = Build();
        h.Candidates.Result = [Book("A")];
        h.Ranker.Gate.Close();

        var pending = h.Service.RecommendAsync(UserId, Requirement, CancellationToken.None);
        await h.Ranker.Gate.Entered;
        h.Time.Advance(TimeSpan.FromSeconds(59));
        Assert.False(pending.IsCompleted);

        h.Ranker.Gate.Release();
        var attempt = await pending;

        Assert.IsType<RecommendationAttempt.Succeeded>(attempt);
        Assert.Single(h.Store.Calls);
    }

    [Fact]
    public async Task Parser_still_waiting_at_60_seconds_times_out_and_no_later_step_runs()
    {
        var h = Build();
        h.Parser.Gate.Close();

        var pending = h.Service.RecommendAsync(UserId, Requirement, CancellationToken.None);
        await h.Parser.Gate.Entered;
        h.Time.Advance(TimeSpan.FromSeconds(60));

        await Assert.ThrowsAsync<AiTimeoutException>(() => pending);
        Assert.Empty(h.Embeddings.Calls);
        Assert.Empty(h.Candidates.Calls);
        AssertNothingSaved(h);
    }

    [Fact]
    public async Task Timeout_logs_one_warning_with_the_elapsed_time_and_the_step_that_was_running()
    {
        var h = Build();
        h.Ranker.Gate.Close();
        h.Candidates.Result = [Book("A")];

        var pending = h.Service.RecommendAsync(UserId, Requirement, CancellationToken.None);
        await h.Ranker.Gate.Entered;
        h.Time.Advance(TimeSpan.FromSeconds(60));
        await Assert.ThrowsAsync<AiTimeoutException>(() => pending);

        var warning = Assert.Single(h.Logger.Entries, e => e.Level == LogLevel.Warning);
        Assert.Equal("ranking", warning.Properties["Step"]);
        Assert.Equal(60000d, warning.Properties["ElapsedMs"]);
        Assert.DoesNotContain(Requirement, warning.Message);
    }

    [Fact]
    public async Task Caller_cancelling_while_the_ranker_waits_propagates_the_cancellation_not_a_timeout()
    {
        var h = Build();
        h.Candidates.Result = [Book("A")];
        h.Ranker.Gate.Close();
        using var cts = new CancellationTokenSource();

        var pending = h.Service.RecommendAsync(UserId, Requirement, cts.Token);
        await h.Ranker.Gate.Entered;
        await cts.CancelAsync();

        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);
        AssertNothingSaved(h);
        Assert.DoesNotContain(h.Logger.Entries, e => e.Level == LogLevel.Warning);
    }

    // ----- AI failure logging (§14) -----

    [Fact]
    public async Task Ranker_ai_failure_logs_one_error_with_the_step_and_elapsed_time_and_rethrows_the_same_exception()
    {
        var h = Build();
        h.Candidates.Result = [Book("A")];
        var error = new AiUnavailableException("OpenAI 推薦排序失敗", new InvalidOperationException("sdk down"));
        h.Ranker.ThrowForAll(error);

        var actual = await Assert.ThrowsAsync<AiUnavailableException>(() => Recommend(h, UserId, Requirement, CancellationToken.None));

        Assert.Same(error, actual);
        AssertNothingSaved(h);
        var entry = Assert.Single(h.Logger.Entries, e => e.Level == LogLevel.Error);
        Assert.Same(error, entry.Exception);
        Assert.Equal("ranking", entry.Properties["Step"]);
        Assert.IsType<double>(entry.Properties["ElapsedMs"]);
        Assert.DoesNotContain(Requirement, entry.Message);
    }

    [Fact]
    public async Task Parser_ai_failure_logs_one_error_naming_the_parsing_step()
    {
        var h = Build();
        var error = new AiUnavailableException("OpenAI 需求解析失敗", new InvalidOperationException("sdk down"));
        h.Parser.ThrowForAll(error);

        var actual = await Assert.ThrowsAsync<AiUnavailableException>(() => Recommend(h, UserId, Requirement, CancellationToken.None));

        Assert.Same(error, actual);
        AssertNothingSaved(h);
        var entry = Assert.Single(h.Logger.Entries, e => e.Level == LogLevel.Error);
        Assert.Equal("parsing", entry.Properties["Step"]);
        Assert.Single(h.Logger.Entries);
    }

    // ----- Book AI profile after the save (#18, recommendation.md §2(10), §9.1) -----

    [Fact]
    public async Task Difficulties_are_read_after_the_save_and_before_the_books_are_queued()
    {
        var h = Build();
        var first = Book("A");
        var second = Book("B");
        h.Candidates.Result = [first, second];

        await Recommend(h, UserId, Requirement, CancellationToken.None);

        Assert.Equal(
            ["save", "read", "find", $"enqueue {first.BookId}", $"enqueue {second.BookId}"],
            h.Events);
    }

    // The ranker port carries only candidate metadata, and no profile read happens before ranking. Reflection on the port's
    // input type is the check: a profile field added to RankingCandidate fails it, and so does reading profiles before ranking.
    [Fact]
    public async Task Ranking_finishes_before_any_profile_is_read_and_the_ranker_input_has_no_profile_fields()
    {
        var h = Build();
        h.Candidates.Result = [Book("A")];

        await Recommend(h, UserId, Requirement, CancellationToken.None);

        Assert.Equal(1, h.Profiles.RankerCallsAtFirstRead);
        Assert.Equal(
            new[]
            {
                "CandidateNo", "Title", "Subtitle", "ContributorNames", "Publisher", "PublishedDate",
                "PublishedDatePrecision", "Subjects", "Description",
            }.Order(),
            typeof(RankingCandidate).GetProperties().Select(property => property.Name).Order());
    }

    [Fact]
    public async Task The_difficulty_read_after_the_save_is_carried_in_the_outcome()
    {
        var h = Build();
        var first = Book("A");
        var second = Book("B");
        h.Candidates.Result = [first, second];
        h.Profiles.Difficulties[first.BookId] = 4;

        var outcome = await Recommend(h, UserId, Requirement, CancellationToken.None);

        Assert.Equal(4, outcome.Difficulties[first.BookId]);
        Assert.False(outcome.Difficulties.ContainsKey(second.BookId));
    }

    [Fact]
    public async Task A_failed_difficulty_read_still_succeeds_with_an_empty_snapshot()
    {
        var h = Build();
        h.Candidates.Result = [Book("A")];
        var error = new InvalidOperationException("profile table down");
        h.Profiles.ReadError = error;

        var outcome = await Recommend(h, UserId, Requirement, CancellationToken.None);

        Assert.Empty(outcome.Difficulties);
        Assert.Single(h.Store.Calls);
        Assert.Contains("find", h.Events);
    }

    [Fact]
    public async Task A_failed_schedule_still_succeeds_and_logs_a_warning_from_the_scheduler()
    {
        var h = Build();
        h.Candidates.Result = [Book("A")];
        var error = new InvalidOperationException("profile lookup down");
        h.Profiles.FindError = error;

        await Recommend(h, UserId, Requirement, CancellationToken.None);

        Assert.Single(h.Store.Calls);
        Assert.Empty(h.Queue.Enqueued);
        var warning = Assert.Single(h.SchedulerLogger.Entries, e => e.Level == LogLevel.Warning);
        Assert.Same(error, warning.Exception);
    }

    [Fact]
    public async Task Zero_results_skip_the_difficulty_read_and_the_scheduling()
    {
        var h = Build();
        h.Candidates.Result = [];

        var outcome = await Recommend(h, UserId, Requirement, CancellationToken.None);

        Assert.Equal(["save"], h.Events);
        Assert.Empty(outcome.Difficulties);
    }

    // The 60 s budget ends at the save. A timer firing while the profile steps wait must not turn the saved search into a timeout.
    [Fact]
    public async Task A_timeout_firing_after_the_save_does_not_turn_the_saved_search_into_a_timeout()
    {
        var h = Build();
        h.Candidates.Result = [Book("A")];
        h.Profiles.ReadGate.Close();

        var pending = h.Service.RecommendAsync(UserId, Requirement, CancellationToken.None);
        // Bounded, so a service that never reads the difficulties fails here instead of waiting forever.
        await h.Profiles.ReadGate.Entered.WaitAsync(TimeSpan.FromSeconds(5));
        h.Time.Advance(TimeSpan.FromSeconds(60));
        h.Profiles.ReadGate.Release();

        var attempt = await pending;

        Assert.IsType<RecommendationAttempt.Succeeded>(attempt);
        Assert.Single(h.Store.Calls);
    }

    // ----- Helpers -----

    private static async Task<RecommendationOutcome> Recommend(Harness h, Guid userId, string requirementText, CancellationToken cancellationToken) =>
        Assert.IsType<RecommendationAttempt.Succeeded>(await h.Service.RecommendAsync(userId, requirementText, cancellationToken)).Outcome;

    private static void AssertNothingSaved(Harness h)
    {
        Assert.Empty(h.Store.Calls);
        Assert.DoesNotContain(h.Logger.Entries, e => e.Level == LogLevel.Information);
    }

    private static RankedItem Item(int candidateNo) => new(candidateNo, 0.9, $"理由 {candidateNo}");

    private static CandidateBook Book(string title, double similarity = 0.8, string? description = "description")
    {
        return new CandidateBook(
            Guid.NewGuid(),
            similarity,
            title,
            null,
            ["作者"],
            ["作者"],
            "出版社",
            new DateOnly(2020, 1, 1),
            PublishedDatePrecision.Day,
            ["海洋"],
            description,
            null);
    }

    private static Harness Build(RecommendationOptions? options = null)
    {
        var parser = new FakeRequirementParser();
        var embeddings = new FakeEmbeddingGenerator();
        var candidates = new FakeCandidateSearch();
        var ranker = new FakeRecommendationRanker();
        // One log shared by the fakes whose call order the tests check: the save, the profile reads and the enqueues.
        var events = new List<string>();
        var store = new FakeRecommendationStore { Saved = new SavedRecommendationSearch(Guid.NewGuid(), SavedAt), Events = events };
        var profiles = new FakeProfileStore(events, ranker);
        var queue = new FakeProfileQueue(events);
        var schedulerLogger = new RecordingLogger<BookProfileScheduler>();
        var scheduler = new BookProfileScheduler(profiles, queue, schedulerLogger, Options.Create(new AiProfileOptions()));
        var logger = new RecordingLogger<RecommendationService>();
        var usage = new FakeRecommendationUsage(parser);
        var time = new FakeTimeProvider(new DateTimeOffset(SavedAt));
        var service = new RecommendationService(
            parser,
            embeddings,
            candidates,
            ranker,
            store,
            usage,
            new BookDifficultyReader(profiles, new RecordingLogger<BookDifficultyReader>()),
            scheduler,
            Options.Create(options ?? new RecommendationOptions()),
            time,
            logger);
        return new Harness(service, parser, embeddings, candidates, ranker, store, usage, profiles, queue, schedulerLogger, logger, time, events);
    }

    private sealed record Harness(
        RecommendationService Service,
        FakeRequirementParser Parser,
        FakeEmbeddingGenerator Embeddings,
        FakeCandidateSearch Candidates,
        FakeRecommendationRanker Ranker,
        FakeRecommendationStore Store,
        FakeRecommendationUsage Usage,
        FakeProfileStore Profiles,
        FakeProfileQueue Queue,
        RecordingLogger<BookProfileScheduler> SchedulerLogger,
        RecordingLogger<RecommendationService> Logger,
        FakeTimeProvider Time,
        List<string> Events);

    // Scripted IBookProfileStore for the profile steps. Reads and finds are recorded in Events. ReadGate holds the difficulty read
    // open, so a test can move fake time while the read is still waiting.
    private sealed class FakeProfileStore(List<string> events, FakeRecommendationRanker ranker) : IBookProfileStore
    {
        public Dictionary<Guid, short> Difficulties { get; } = [];
        public Exception? ReadError { get; set; }
        public Exception? FindError { get; set; }
        public CallGate ReadGate { get; } = new();

        // How many ranker calls had happened when the first profile read started. 0 would mean a read happened before ranking.
        public int RankerCallsAtFirstRead { get; private set; } = -1;

        public Task<IReadOnlyList<Guid>> FindStaleAsync(IReadOnlyCollection<Guid> bookIds, CancellationToken cancellationToken)
        {
            events.Add("find");
            if (FindError is not null)
                return Task.FromException<IReadOnlyList<Guid>>(FindError);

            return Task.FromResult<IReadOnlyList<Guid>>(bookIds.ToList());
        }

        public async Task<IReadOnlyDictionary<Guid, short>> ReadDifficultiesAsync(IReadOnlyCollection<Guid> bookIds, CancellationToken cancellationToken)
        {
            if (RankerCallsAtFirstRead < 0)
                RankerCallsAtFirstRead = ranker.Calls.Count;
            events.Add("read");

            await ReadGate.PassAsync(cancellationToken);
            if (ReadError is not null)
                throw ReadError;

            return bookIds.Where(Difficulties.ContainsKey).ToDictionary(id => id, id => Difficulties[id]);
        }

        public Task<BookProfileSource?> LoadSourceAsync(Guid bookId, CancellationToken cancellationToken) => throw new NotSupportedException();

        public Task UpsertAsync(
            Guid bookId,
            GeneratedBookProfile profile,
            string sourceContentHash,
            string modelName,
            string promptVersion,
            CancellationToken cancellationToken) => throw new NotSupportedException();
    }

    // Records every enqueue in Events, so the order against the save and the reads can be checked.
    private sealed class FakeProfileQueue(List<string> events) : IBookProfileQueue
    {
        public List<Guid> Enqueued { get; } = [];

        public bool TryEnqueue(Guid bookId)
        {
            events.Add($"enqueue {bookId}");
            Enqueued.Add(bookId);
            return true;
        }

        public IAsyncEnumerable<Guid> ReadAllAsync(CancellationToken cancellationToken) => throw new NotSupportedException();

        public void Complete(Guid bookId) => throw new NotSupportedException();
    }

    // Scripted IRecommendationUsage. Count is the number of searches already saved today; every request is recorded.
    private sealed class FakeRecommendationUsage(FakeRequirementParser parser) : IRecommendationUsage
    {
        public int Count { get; set; }
        public List<Call> Calls { get; } = [];

        // How many parser calls had happened when the count ran. 0 means the limit was checked before any parsing.
        public int ParserCallsBeforeCount { get; private set; } = -1;

        public Task<int> CountSinceAsync(Guid userId, DateTime sinceUtc, CancellationToken cancellationToken)
        {
            Calls.Add(new Call(userId, sinceUtc));
            ParserCallsBeforeCount = parser.Calls.Count;
            return Task.FromResult(Count);
        }

        public sealed record Call(Guid UserId, DateTime SinceUtc);
    }

    // Scripted ICandidateSearch. Records every call, including calls that threw, and returns Result unless Error is set.
    private sealed class FakeCandidateSearch : ICandidateSearch
    {
        public List<Call> Calls { get; } = [];
        public IReadOnlyList<CandidateBook> Result { get; set; } = [];
        public Exception? Error { get; set; }

        public Task<IReadOnlyList<CandidateBook>> FindAsync(
            RequirementFilters filters,
            float[] queryVector,
            double threshold,
            int topK,
            CancellationToken cancellationToken)
        {
            Calls.Add(new Call(filters, queryVector, threshold, topK));

            if (Error is not null)
                return Task.FromException<IReadOnlyList<CandidateBook>>(Error);

            return Task.FromResult(Result);
        }

        public sealed record Call(RequirementFilters Filters, float[] QueryVector, double Threshold, int TopK);
    }

    // Scripted IRecommendationStore. Records every attempt; Saved is returned only when Error is null.
    private sealed class FakeRecommendationStore : IRecommendationStore
    {
        public List<Call> Calls { get; } = [];
        public SavedRecommendationSearch Saved { get; init; } = new(Guid.Empty, DateTime.MinValue);
        public List<string>? Events { get; init; }
        public Exception? Error { get; set; }

        public Task<SavedRecommendationSearch> SaveAsync(
            Guid userId,
            string requirementText,
            IReadOnlyList<RankedCandidate> results,
            CancellationToken cancellationToken)
        {
            Calls.Add(new Call(userId, requirementText, results));
            Events?.Add("save");

            if (Error is not null)
                return Task.FromException<SavedRecommendationSearch>(Error);

            return Task.FromResult(Saved);
        }

        public sealed record Call(Guid UserId, string RequirementText, IReadOnlyList<RankedCandidate> Results);
    }

    // Keeps the formatted message and the structured properties so tests can assert field values, not only text.
    private sealed class RecordingLogger<T> : ILogger<T>
    {
        public List<Entry> Entries { get; } = [];

        public IDisposable? BeginScope<TState>(TState state) where TState : notnull => null;

        public bool IsEnabled(LogLevel logLevel) => true;

        public void Log<TState>(LogLevel logLevel, EventId eventId, TState state, Exception? exception, Func<TState, Exception?, string> formatter)
        {
            var properties = (state as IEnumerable<KeyValuePair<string, object?>>) ?? [];
            Entries.Add(new Entry(logLevel, formatter(state, exception), exception, properties.ToDictionary(p => p.Key, p => p.Value)));
        }

        public sealed record Entry(LogLevel Level, string Message, Exception? Exception, IReadOnlyDictionary<string, object?> Properties);
    }
}
