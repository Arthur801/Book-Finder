# BuildKit is required for ADD --checksum. Do not add a `# syntax=` line: it would pull an unpinned frontend image.
# The SDK is not published as a pinned MCR image for this version, so it is installed from a checksummed tarball.
# DOTNET_SDK_VERSION must equal global.json sdk.version (see .github/scripts/check_version_sync.py).
ARG DOTNET_SDK_VERSION=10.0.113

FROM mcr.microsoft.com/dotnet/runtime-deps:10.0.13-noble@sha256:1c20bc9ebda297198be069d82b6c5d1716faeeec8b8dca53ef963f9c92d3e2e3 AS build
ARG DOTNET_SDK_VERSION
ADD --checksum=sha256:4118405267040ea20104afc0653a214b83b3a19cef5c01e962b1fa5454bdfd53 \
    https://builds.dotnet.microsoft.com/dotnet/Sdk/${DOTNET_SDK_VERSION}/dotnet-sdk-${DOTNET_SDK_VERSION}-linux-x64.tar.gz \
    /tmp/dotnet-sdk.tar.gz
RUN mkdir -p /usr/share/dotnet \
    && tar -C /usr/share/dotnet -xzf /tmp/dotnet-sdk.tar.gz \
    && rm /tmp/dotnet-sdk.tar.gz
ENV DOTNET_ROOT=/usr/share/dotnet \
    PATH=/usr/share/dotnet:$PATH \
    DOTNET_CLI_TELEMETRY_OPTOUT=1 \
    DOTNET_NOLOGO=1
WORKDIR /src

# Restore from the project files alone so source edits do not invalidate the NuGet layer.
COPY global.json dotnet-tools.json Book-Finder.csproj ./
RUN dotnet restore Book-Finder.csproj && dotnet tool restore

COPY . .
RUN dotnet publish Book-Finder.csproj --configuration Release -o /out/app --no-restore

# The bundle and SQL scripts need a DbContext, and Program.cs throws without a connection string. The placeholder is
# set per RUN only, so it never becomes an image ENV.
RUN export ConnectionStrings__DefaultConnection=Host=placeholder \
    && dotnet ef migrations bundle --configuration Release -o /out/app/efbundle

# Migration source hashes for the release manifest; the list cross-checks that EF sees the same migrations.
RUN bash deploy/release/build-manifest.sh Infrastructure/Persistence/Migrations /out/release \
    && export ConnectionStrings__DefaultConnection=Host=placeholder \
    && dotnet ef migrations list --no-connect --no-build --configuration Release \
        | grep -oE '^[0-9]{14}_[A-Za-z0-9]+' > /tmp/ef-migrations.txt \
    && cut -d' ' -f1 /out/release/migrations.txt | diff - /tmp/ef-migrations.txt \
    && echo "migration list matches manifest"

# One idempotent script per migration, each from the previous migration, so a deploy can stop at any boundary.
RUN export ConnectionStrings__DefaultConnection=Host=placeholder \
    && mkdir -p /out/release/sql \
    && prev=0 \
    && for id in $(cut -d' ' -f1 /out/release/migrations.txt); do \
         dotnet ef migrations script "$prev" "$id" --idempotent --no-build --configuration Release -o "/out/release/sql/$id.sql"; \
         prev="$id"; \
       done \
    && cd /out/release/sql && sha256sum ./*.sql | sed 's#  \./#  #' > SHA256SUMS

FROM mcr.microsoft.com/dotnet/aspnet:10.0.13-noble@sha256:8af87eba5e7cdafb1514d7388be287365da97c132509e84dfe252ffd552398ca AS final
ARG GIT_COMMIT=unknown
LABEL org.opencontainers.image.source=https://github.com/Arthur801/Book-Finder \
      org.opencontainers.image.revision=$GIT_COMMIT

WORKDIR /app
COPY --from=build /out/app ./
COPY --from=build /out/release /opt/release
# Antiforgery and auth cookies must survive a container replacement; the named volume is mounted here at run time.
RUN install -d -o app -g app /data-protection-keys

ENV ASPNETCORE_HTTP_PORTS=8080
EXPOSE 8080
USER $APP_UID
ENTRYPOINT ["dotnet", "Book-Finder.dll"]
