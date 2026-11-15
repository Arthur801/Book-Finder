using Book_Finder.Domain.Entities;

namespace Book_Finder.Application.Identity;

// One queued account mail request (plan member-center C3, D-B). Email is personal data: never log the whole record.
public sealed record AccountEmailRequest(AccountActionTokenPurpose Purpose, string Email);

// Hands a request to the background worker without waiting for it, so a POST answers in the same time whatever the account state.
// The Purpose field selects the mail: resend verification (C3) and forgot password (C4) share this queue.
public interface IAccountEmailQueue
{
    // False when the queue is full; the request is dropped. The caller still gives the same answer to the user.
    bool TryEnqueue(AccountEmailRequest request);
}
