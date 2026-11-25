# Contributing

Paperproof is source-available under the Functional Source License 1.1, ALv2 Future License (`FSL-1.1-ALv2`). By opening a pull request, you agree that your contribution is licensed under the same terms and that you have the right to submit it.

Before opening a pull request:

- Run `make check`. Lint, types, tests, and the golden set must pass.
- Add a unit test for any change to `extract/verify.py`. The verifier is the product.
- Add an eval case for any change to extraction behavior.
- Keep the invariants in `AGENTS.md` intact.
- Use plain, active prose. No em dashes.

For a competing-use license or another commercial arrangement, open an issue at https://github.com/jimmerioles/paperproof/issues.
