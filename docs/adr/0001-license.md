# 0001: Use FSL-1.1-ALv2 for a commercial product

Status: Accepted
Date: 2026-11-25

## Context

Paperproof may become a commercial product. The source should stay public so users can inspect the citation verifier and run the tool themselves, but a competitor should not be able to take the code and offer it as a competing hosted service during the early commercial period.

The project also needs a license that a small team can adopt without a CLA, a legal review, or a custom contract for every user.

## Decision

Use the Functional Source License 1.1, ALv2 Future License (`FSL-1.1-ALv2`).

- Source is public and usable, including internal commercial use.
- A competing commercial product or service is not a permitted purpose.
- Each version converts to Apache 2.0 two years after publication.
- Contributions are accepted under the same license, without a CLA.
- The project is described as source-available, not OSI open source.

## Consequences

Easier:

- Users can inspect the verifier and self-host for internal work.
- A competitor cannot clone the hosted product during the protected period.
- No CLA or dual-license administration is required to keep the project under FSL.
- The code becomes fully permissive after two years, which limits long-term lock-in.

Harder:

- Some enterprises treat any non-OSI license as a procurement exception.
- GitHub reports the license as "Other" because its detector does not know FSL.
- If the project later wants to relicense contributed code or sell a proprietary exception that covers contributions, it will need permission from contributors. A CLA would need to be added before accepting outside code.

## Alternatives considered

- **MIT**: maximum adoption, no protection against a hosted clone.
- **Apache 2.0**: same as MIT plus a patent grant, still no protection against a hosted clone.
- **AGPL-3.0 plus a commercial license**: strong protection, but more enterprise friction and requires a CLA to preserve dual licensing.
- **Business Source License 1.1**: similar protection, but less standard than FSL and requires custom parameters.
