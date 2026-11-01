# Documentation site

The documentation is a VitePress site in `docs/`. It is published to `https://unixnu.com`.

## Requirements

| Tool | Version |
| --- | --- |
| Node.js | 22 or newer |
| npm | 10 or newer |

## Local development

```sh
cd docs
npm install
npm run dev
```

The site runs at the URL printed by VitePress. `npm run build` writes the static site to `docs/.vitepress/dist`. `npm run preview` serves the built site.

## Structure

```
docs/
  .vitepress/
    config.mts          site configuration
    theme/              custom CSS
  public/
    CNAME               custom domain
    logo-light.svg
    logo-dark.svg
  guide/                getting started and build
  concepts/             boot chain, payload, prelink, userdata, security
  porting/              device porting
  drivers/              UEFI, XNU and kext drivers
  xnu/                  source, patches, pages, boot arguments
  devices/              device pages and examples
  reference/            command line, configuration, outputs, QEMU, glossary
  contributing/         this section
  zh/                   Simplified Chinese locale
```

## Add a page

1. Create the Markdown file under the matching section.
2. Add the page to the sidebar in `docs/.vitepress/config.mts`.
3. Add the Chinese page under `docs/zh/` and to the Chinese sidebar.
4. Run `npm run build` and fix broken links.
5. Add the language switcher entry when a new section starts.

## Language editions

The site has two locales:

| Locale | Path | Language |
| --- | --- | --- |
| Root | `/` | English |
| `zh` | `/zh/` | Simplified Chinese |

Both editions carry the same pages. A change to one page updates both editions in the same pull request.

## Writing rules

- Use standard technical terms.
- State the current behavior directly.
- Avoid em-dashes and en-dashes.
- Avoid metaphors.
- Use neutral headings.
- Keep the page focused on one subject.
- Use tables for references and lists for steps.
- Put device-specific values in the device page.
- Put a concrete command in every procedure.

## Deploy

The workflow `.github/workflows/docs.yml` builds the site on every push to `main` that touches `docs/` and deploys it with GitHub Pages.

The site needs:

1. GitHub Pages enabled with `GitHub Actions` as the source.
2. The custom domain `unixnu.com` in the repository Pages settings.
3. DNS records for the domain.

`docs/public/CNAME` contains:

```
unixnu.com
```

DNS for an apex domain:

| Type | Name | Value |
| --- | --- | --- |
| A | `@` | `185.199.108.153` |
| A | `@` | `185.199.109.153` |
| A | `@` | `185.199.110.153` |
| A | `@` | `185.199.111.153` |
| CNAME | `www` | `unixnu.github.io` |

GitHub Pages also serves the site over IPv6:

| Type | Name | Value |
| --- | --- | --- |
| AAAA | `@` | `2606:50c0:8000::153` |
| AAAA | `@` | `2606:50c0:8001::153` |
| AAAA | `@` | `2606:50c0:8002::153` |
| AAAA | `@` | `2606:50c0:8003::153` |

Enable `Enforce HTTPS` after the certificate is issued.

## Badge

The README uses:

```markdown
[![Documentation](https://img.shields.io/badge/docs-unixnu.com-2A5BD7?logo=readthedocs&logoColor=white)](https://unixnu.com)
```

## Link check

```sh
cd docs
npm run build
```

VitePress fails the build on a broken internal link.

## Next steps

- [Repository layout](/contributing/repository)
- [Overview](/guide/overview)
