# Workflow

How work goes from an idea to a release in this repo. Setup and commands are in the [README](../README.md), code rules in [AGENTS.md](../AGENTS.md) and testing in [TESTING.md](../TESTING.md).

Team: Yashwanth, Annie, Dayana, Laya, Shini.

## Branches

| Branch | What it holds | Who changes it |
| --- | --- | --- |
| `milestone-3` | Current work for the final release (Level 5) | PRs only, never a direct push |
| `yashwanth` | The review release (milestone 2) as submitted | Nobody, frozen |
| `main` | Milestone 1 as submitted | Nobody, frozen |
| `milestone-*-base` | The starting point of each milestone, so staff can see what each milestone changed | Nobody |

Each milestone has one open PR from its work branch into its base (#13 for milestone 1, #14 for milestone 2, #19 for milestone 3). These PRs stay **open** for the TA and professor and are never merged.

## Picking work

- At the start of each milestone the team splits the handout into one task per person: **one code PR, one doc or job, and one PR to review**. The plan is posted in the team chat with an owner for each task and the merge order.
- Each person has **one PR open at a time** for their code task. Docs can go in a second PR.
- Work that the plan missed (a bug found while reviewing, a sister-team comment) goes to whoever owns that area. If it is outside everyone's task, it is raised in the team chat and the first person free picks it up.
- Urgent fixes (a broken `milestone-3`, a failing CI) come before new features. Whoever finds it says so in the chat first, so two people don't fix the same thing.

## From branch to merge

| Step | What happens | Owner |
| --- | --- | --- |
| 1. Branch | `git checkout milestone-3 && git pull`, then `git checkout -b <name>/<topic>` | Author |
| 2. Build | Code, tests and docs in the same PR. Run `python -m pytest`, `ruff check .`, `mypy app` | Author |
| 3. Catch up | `git fetch origin && git merge origin/milestone-3`, fix any conflicts, rerun the checks | Author |
| 4. Open PR | Base **`milestone-3`**. Fill in every section of the PR template, link the issue or review comment it answers, and say if AI was used | Author |
| 5. Review | The assigned reviewer pulls the branch, runs the checks, reads the diff, and approves or requests changes | Reviewer from the plan |
| 6. Merge | Someone **other than the author** merges, after approval and green CI | Reviewer or any other teammate |
| 7. Tell the team | Post in the chat that it merged, so others catch up before their next push | Whoever merged |

Required before merging:

- CI is green: `pytest`, `ruff check .` and `mypy app`.
- One approving review from a teammate who is not the author.
- For changes to `app/providers/dropbox/`: the author has also run `python -m pytest tests/integration -v` against real Dropbox and says so in the PR.
- The README is updated if the change is user-visible (a route, an error code, a setup step).

## Releases

### Version names

`vMAJOR.MINOR.PATCH`, with a pre-release suffix for review releases.

- **MINOR** goes up when a milestone adds behaviour (new routes, new error codes).
- **PATCH** goes up for fixes that don't change what a caller sees.
- **MAJOR** stays `1` for HW1. It would go up if a route or response shape changed in a way that breaks existing callers.
- A review release gets `-rc.N` (e.g. `v1.1.0-rc.1`) and is marked as a **prerelease** on GitHub.

Earlier tags were named without the `v`: `1.0.0` (milestone 1) and `1.0.1` (milestone 2). They stay as they are, because published tags are never moved or renamed. From the final release on, tags use the `v` prefix: **`v1.1.0`**.

Changes that affect callers (a new error code, a stricter path rule) are listed under "Changes" in the release notes. A breaking change gets its own "Breaking changes" section with what callers must do.

### Making a release

The coordinator is chosen in the milestone plan, and is a different person for each release.

1. **Freeze.** When all code and doc PRs in the plan are merged, the coordinator announces a freeze on `milestone-3`. Nothing else merges until the release is out.
2. **Check the exact commit.** Note the commit hash on `milestone-3`, and check CI passed on that commit.
3. **Tag it** with an annotated tag and push it:
   ```bash
   git checkout milestone-3 && git pull
   git tag -a v1.1.0 -m "Final release: Level 5"
   git push origin v1.1.0
   ```
4. **Verify from a fresh checkout.** A different teammate (the verifier) clones the repo at the tag into a new folder, follows only the README, runs the fast tests and one real workflow (upload, read, move, delete against Dropbox), and posts the result in the chat.
5. **Publish a GitHub Release** for the tag (Releases → Draft a new release). The notes cover: user-visible changes, linked PRs and issues, breaking changes, setup or configuration changes, known limitations, and links to the CI run and the verification. Review auto-generated notes before publishing. Mark review releases as prerelease.
6. **Submit** the release link, tag and commit hash.

| Release | Tag | Coordinator | Verifier |
| --- | --- | --- | --- |
| Milestone 1 | `1.0.0` | Dayana | Not recorded |
| Review (milestone 2) | `1.0.1` | Shini (tag created by Dayana) | Dayana |
| Final (milestone 3) | `v1.1.0` | Yashwanth | Dayana |

### A defective release

- Never move or delete a published tag. The fix goes into a new version (e.g. `v1.1.1`).
- The coordinator edits the broken release's notes to say what is wrong and whether to go back to the previous version or wait for the fix.
- Reverting code does not undo state. Files a broken build wrote to Dropbox stay there, and `.env` changes (e.g. new credentials a release required) stay too. The notes must say what has to be cleaned up or changed by hand.

## What we changed after the review release

**Observation:** in milestone 2 the plan said "P1 merges first", but other PRs were opened before P1's cleanup PR (#8) landed. #9 then conflicted with #8 in `README.md` and `download.py`, and was fixed by hand after the fact. Separately, the sister-team review found that #3 was merged with the PR template still unfilled.

**Adjustment:** step 3 (merge the latest `milestone-3` and rerun the checks before opening a PR) and step 7 (announce merges in the chat) were added, and reviewers now request changes on a PR whose template isn't filled in. Milestone 3 work also moved to its own branch, `milestone-3`, so the submitted review release on `yashwanth` stays unchanged.
