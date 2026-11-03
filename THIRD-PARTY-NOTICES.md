# サードパーティー

ReadingRepairの独自コードはMIT Licenseです。VoiSona Talk、各音声・LLMサービス、Whisperモデルは同梱せず、それぞれの利用条件に従います。

配布ZIPはPython 3.12、.NET 10 Windows Desktop、faster-whisper、CTranslate2、PyAVと付属FFmpegライブラリ、ONNX Runtime、tokenizers、NumPy等のランタイムを含みます。各配布物のライセンス・著作権表示を`third-party`へ収集します。完全なビルド依存一覧は`requirements-build.txt`です。

PyInstallerはビルド時に使用し、配布時はブートローダーと実行フックを含みます。PyInstallerの例外条項を含むライセンスを`third-party/python-packages/pyinstaller`へ同梱します。PyAVホイール付属のライブラリの表示はPyAVのdist-infoおよび関連ライセンスから収集します。

Python/.NET/Pythonパッケージの上流ライセンスが独自コードのMIT条件より優先されます。モデル、キー、原文、辞書、生成音声、検証用履歴は配布対象ではありません。
