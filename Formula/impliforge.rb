class Impliforge < Formula
  include Language::Python::Virtualenv

  desc "Orchestrator-centric multi-agent workflow runner built on the GitHub Copilot SDK"
  homepage "https://pypi.org/project/impliforge/"
  url "https://github.com/rioriost/impliforge/releases/download/0.1.0/impliforge-0.1.0.tar.gz"
  sha256 "f03f757eb5bb5fe66b52d1a5afdb713b82d6dd3bb285c53c66d247ef23ef0021"
  license "MIT"

  depends_on "python@3.14"
  resource "annotated-types" do
    url "https://files.pythonhosted.org/packages/78/b6/6307fbef88d9b5ee7421e68d78a9f162e0da4900bc5f5793f6d3d0e34fb8/annotated_types-0.7.0-py3-none-any.whl"
    sha256 "1f02e8b43a8fbbc3f3e0d4f0f4bfc8131bcb4eebe8849b8e5c773f3a1c582a53"
  end
  resource "github-copilot-sdk" do
    if OS.mac? && Hardware::CPU.arm?
      url "https://files.pythonhosted.org/packages/04/04/d2e8bf4587c4da270ccb9cbd5ab8a2c4b41217c2bf04a43904be8a27ae20/github_copilot_sdk-0.2.1-py3-none-macosx_11_0_arm64.whl"
      sha256 "ef7ff68eb8960515e1a2e199ac0ffb9a17cd3325266461e6edd7290e43dcf012"
    elsif OS.mac? && Hardware::CPU.intel?
      url "https://files.pythonhosted.org/packages/67/41/76a9d50d7600bf8d26c659dc113be62e4e56e00a5cbfd544e1b5b200f45c/github_copilot_sdk-0.2.1-py3-none-macosx_10_9_x86_64.whl"
      sha256 "c0823150f3b73431f04caee43d1dbafac22ae7e8bd1fc83727ee8363089ee038"
    elsif OS.linux?
      url "https://files.pythonhosted.org/packages/cf/ee/facf04e22e42d4bdd4fe3d356f3a51180a6ea769ae2ac306d0897f9bf9d9/github_copilot_sdk-0.2.1-py3-none-manylinux_2_28_x86_64.whl"
      sha256 "6502be0b9ececacbda671835e5f61c7aaa906c6b8657ee252cad6cc8335cac8e"
    else
      url "https://files.pythonhosted.org/packages/04/04/d2e8bf4587c4da270ccb9cbd5ab8a2c4b41217c2bf04a43904be8a27ae20/github_copilot_sdk-0.2.1-py3-none-macosx_11_0_arm64.whl"
      sha256 "ef7ff68eb8960515e1a2e199ac0ffb9a17cd3325266461e6edd7290e43dcf012"
    end
  end
  resource "pydantic" do
    url "https://files.pythonhosted.org/packages/5a/87/b70ad306ebb6f9b585f114d0ac2137d792b48be34d732d60e597c2f8465a/pydantic-2.12.5-py3-none-any.whl"
    sha256 "e561593fccf61e8a20fc46dfc2dfe075b8be7d0188df33f221ad1f0139180f9d"
  end
  resource "pydantic-core" do
    if OS.mac? && Hardware::CPU.arm?
      url "https://files.pythonhosted.org/packages/74/1a/145646e5687e8d9a1e8d09acb278c8535ebe9e972e1f162ed338a622f193/pydantic_core-2.41.5-cp314-cp314-macosx_11_0_arm64.whl"
      sha256 "1d1d9764366c73f996edd17abb6d9d7649a7eb690006ab6adbda117717099b14"
    elsif OS.mac? && Hardware::CPU.intel?
      url "https://files.pythonhosted.org/packages/ea/28/46b7c5c9635ae96ea0fbb779e271a38129df2550f763937659ee6c5dbc65/pydantic_core-2.41.5-cp314-cp314-macosx_10_12_x86_64.whl"
      sha256 "3f37a19d7ebcdd20b96485056ba9e8b304e27d9904d233d7b1015db320e51f0a"
    elsif OS.linux?
      url "https://files.pythonhosted.org/packages/4c/d2/ef2074dc020dd6e109611a8be4449b98cd25e1b9b8a303c2f0fca2f2bcf7/pydantic_core-2.41.5-cp314-cp314-manylinux_2_17_x86_64.manylinux2014_x86_64.whl"
      sha256 "22f0fb8c1c583a3b6f24df2470833b40207e907b90c928cc8d3594b76f874375"
    else
      url "https://files.pythonhosted.org/packages/74/1a/145646e5687e8d9a1e8d09acb278c8535ebe9e972e1f162ed338a622f193/pydantic_core-2.41.5-cp314-cp314-macosx_11_0_arm64.whl"
      sha256 "1d1d9764366c73f996edd17abb6d9d7649a7eb690006ab6adbda117717099b14"
    end
  end
  resource "python-dateutil" do
    url "https://files.pythonhosted.org/packages/ec/57/56b9bcc3c9c6a792fcbaf139543cee77261f3651ca9da0c93f5c1221264b/python_dateutil-2.9.0.post0-py2.py3-none-any.whl"
    sha256 "a8b2bc7bffae282281c8140a97d3aa9c14da0b136dfe83f850eea9a5f7470427"
  end
  resource "six" do
    url "https://files.pythonhosted.org/packages/b7/ce/149a00dd41f10bc29e5921b496af8b574d8413afcd5e30dfa0ed46c2cc5e/six-1.17.0-py2.py3-none-any.whl"
    sha256 "4721f391ed90541fddacab5acf947aa0d3dc7d27b2e1e8eda2be8970586c3274"
  end
  resource "typing-extensions" do
    url "https://files.pythonhosted.org/packages/18/67/36e9267722cc04a6b9f15c7f3441c2363321a3ea07da7ae0c0707beb2a9c/typing_extensions-4.15.0-py3-none-any.whl"
    sha256 "f0fa19c6845758ab08074a0cfa8b7aecb71c999ca73d62883bc25cc018c4e548"
  end
  resource "typing-inspection" do
    url "https://files.pythonhosted.org/packages/dc/9b/47798a6c91d8bdb567fe2698fe81e0c6b7cb7ef4d13da4114b41d239f65d/typing_inspection-0.4.2-py3-none-any.whl"
    sha256 "4ed1cacbdc298c220f1bd249ed5287caa16f34d44ef4e9c3d0cbad5b521545e7"
  end

  def install
    if OS.mac?
      ENV.append "LDFLAGS", "-Wl,-headerpad_max_install_names"
      ENV.append "RUSTFLAGS", "-C link-arg=-Wl,-headerpad_max_install_names"
    end

    venv = virtualenv_create(libexec, "python3.14")

    resource("annotated-types").stage do
      wheel = Dir["*.whl"].first
      if wheel
        venv.pip_install Pathname(wheel)
      else
        venv.pip_install Pathname.pwd
      end
    end

    resource("github-copilot-sdk").stage do
      if OS.mac? && Hardware::CPU.arm?
        venv.pip_install Pathname(Dir["*.whl"].first)
      elsif OS.mac? && Hardware::CPU.intel?
        venv.pip_install Pathname(Dir["*.whl"].first)
      elsif OS.linux?
        venv.pip_install Pathname(Dir["*.whl"].first)
      else
        venv.pip_install Pathname.pwd
      end
    end

    resource("pydantic").stage do
      wheel = Dir["*.whl"].first
      if wheel
        venv.pip_install Pathname(wheel)
      else
        venv.pip_install Pathname.pwd
      end
    end

    resource("pydantic-core").stage do
      if OS.mac? && Hardware::CPU.arm?
        venv.pip_install Pathname(Dir["*.whl"].first)
      elsif OS.mac? && Hardware::CPU.intel?
        venv.pip_install Pathname(Dir["*.whl"].first)
      elsif OS.linux?
        venv.pip_install Pathname(Dir["*.whl"].first)
      else
        venv.pip_install Pathname.pwd
      end
    end

    resource("python-dateutil").stage do
      wheel = Dir["*.whl"].first
      if wheel
        venv.pip_install Pathname(wheel)
      else
        venv.pip_install Pathname.pwd
      end
    end

    resource("six").stage do
      wheel = Dir["*.whl"].first
      if wheel
        venv.pip_install Pathname(wheel)
      else
        venv.pip_install Pathname.pwd
      end
    end

    resource("typing-extensions").stage do
      wheel = Dir["*.whl"].first
      if wheel
        venv.pip_install Pathname(wheel)
      else
        venv.pip_install Pathname.pwd
      end
    end

    resource("typing-inspection").stage do
      wheel = Dir["*.whl"].first
      if wheel
        venv.pip_install Pathname(wheel)
      else
        venv.pip_install Pathname.pwd
      end
    end

    venv.pip_install buildpath
    bin.install_symlink libexec/"bin/impliforge"
  end

  test do
    system "#{bin}/impliforge", "--help"
  end
end
