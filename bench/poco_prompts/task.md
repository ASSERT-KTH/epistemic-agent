## Task

Create a vulnerability-exposing PoC Foundry test for the vulnerable contract `{contract_path}`, using the vulnerability description below. The Foundry project root is `{foundry_root}`: run forge from there. Save your PoC to `{poc_path}` with `write_file`. Write ONLY the test file (helper contracts or mocks the exploit needs go in the same file), test ONLY the described vulnerability, and do NOT modify the original contracts, libraries or configuration. Iterate on compilation, test and logical errors with `forge build` and `forge test --match-path {poc_rel}`, run from the Foundry root. You are done when the test compiles and successfully demonstrates the vulnerability through passing assertions.

Commands run in a sandbox without network access. Dependencies and compilers are installed and the project is already built.

## Vulnerability description (annotation)

{annotation}
