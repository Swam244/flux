# Automating Windows Builds with GitHub Actions

To support Windows users, you need to compile your C++ code into a "wheel" format that Windows understands. The best way to do this is using **GitHub Actions**.

This guide will set up a system where **every time you push a new version tag (e.g., `v0.1.11`), GitHub will automatically:**
1.  Spin up Windows, Linux, and Mac servers.
2.  Build the wheels for all Python versions.
3.  Upload them strictly to PyPI.

## Step 1: Get a PyPI Token

You need to give GitHub permission to upload to PyPI on your behalf.

1.  Log in to [PyPI](https://pypi.org/).
2.  Go to **Account settings** > **API tokens**.
3.  Click **"Add API token"**.
    - **Token name**: `GitHub Actions` (or anything you like).
    - **Scope**: Select "Project: flux-limiter" (safer) or "Entire account".
4.  **Copy the token value** (it starts with `pypi-`). You won't see it again!

## Step 2: Add Token to GitHub Secrets

1.  Go to your GitHub repository for `flux`.
2.  Navigate to **Settings** > **Secrets and variables** > **Actions**.
3.  Click **"New repository secret"**.
4.  **Name**: `PYPI_API_TOKEN` (Must match the workflow exactly).
5.  **Secret**: Paste the token you copied from PyPI.
6.  Click **"Add secret"**.

## Step 3: Create the Workflow File

Create a new file in your project at this exact path:  
`.github/workflows/upload_to_pypi.yml`

Copy and paste this content:

```yaml
name: Build and Publish to PyPI

on:
  push:
    tags:
      - 'v*'  # Trigger only on tags starting with 'v' (e.g., v0.1.11)

jobs:
  build_wheels:
    name: Build wheels on ${{ matrix.os }}
    runs-on: ${{ matrix.os }}
    strategy:
      matrix:
        # Build on Windows, Linux, and macOS
        os: [ubuntu-latest, windows-latest, macos-latest]

    steps:
      - uses: actions/checkout@v4

      # Used to build C++ extensions
      - name: Build wheels
        uses: pypa/cibuildwheel@v2.16.2
        env:
          # Optional constraints: skip older python versions if needed
          # CIBW_SKIP: "cp36-* cp37-* pp*"
          CIBW_ARCHS_MACOS: x86_64 arm64

      - uses: actions/upload-artifact@v3
        with:
          path: ./wheelhouse/*.whl

  build_sdist:
    name: Build source distribution
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Build sdist
        run: pipx run build --sdist

      - uses: actions/upload-artifact@v3
        with:
          path: dist/*.tar.gz

  publish:
    name: Upload to PyPI
    needs: [build_wheels, build_sdist]
    runs-on: ubuntu-latest
    permissions:
      id-token: write  # IMPORTANT: Mandatory for trusted publishing
      
    steps:
      - uses: actions/download-artifact@v3
        with:
          name: artifact
          path: dist

      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@v1.8.11
        with:
          password: ${{ secrets.PYPI_API_TOKEN }}
```

## Step 4: Trigger a Release

Now, everything is ready. To trigger a build:

1.  **Commit** your changes (update version numbers in `pyproject.toml` etc).
    ```bash
    git add .
    git commit -m "Prepare release v0.1.11"
    ```
2.  **Tag** the commit.
    ```bash
    git tag v0.1.11
    ```
3.  **Push** the tag.
    ```bash
    git push origin v0.1.11
    ```

GitHub Actions will start running. You can watch the progress in the **"Actions"** tab of your repo. When it turns green, your new version will be live on PyPI with Windows support!
