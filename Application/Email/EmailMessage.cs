namespace Book_Finder.Application.Email;

// One outgoing message. Text and HTML bodies are both required so every mail has a plain-text alternative. Bodies may carry
// one-time links, so senders and loggers must never write them out.
public sealed record EmailMessage(string To, string Subject, string TextBody, string HtmlBody);
