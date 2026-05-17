"use strict";
/**
 * CodeGraph Type Definitions
 *
 * Core types for the semantic knowledge graph system.
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.DEFAULT_CONFIG = void 0;
/**
 * Default configuration values
 */
exports.DEFAULT_CONFIG = {
    version: 1,
    rootDir: '.',
    include: [
        // TypeScript/JavaScript
        '**/*.ts',
        '**/*.tsx',
        '**/*.js',
        '**/*.jsx',
        // Python
        '**/*.py',
        // Go
        '**/*.go',
        // Rust
        '**/*.rs',
        // Java
        '**/*.java',
        // C/C++
        '**/*.c',
        '**/*.h',
        '**/*.cpp',
        '**/*.hpp',
        '**/*.cc',
        '**/*.cxx',
        // C#
        '**/*.cs',
        // PHP
        '**/*.php',
        // Ruby
        '**/*.rb',
        // Swift
        '**/*.swift',
        // Kotlin
        '**/*.kt',
        '**/*.kts',
        // Dart
        '**/*.dart',
        // Svelte
        '**/*.svelte',
        // Liquid (Shopify themes)
        '**/*.liquid',
        // Pascal / Delphi
        '**/*.pas',
        '**/*.dpr',
        '**/*.dpk',
        '**/*.lpr',
        '**/*.dfm',
        '**/*.fmx',
    ],
    exclude: [
        // Version control
        '**/.git/**',
        // Dependencies
        '**/node_modules/**',
        '**/vendor/**',
        '**/Pods/**',
        // Generic build outputs
        '**/dist/**',
        '**/build/**',
        '**/out/**',
        '**/bin/**',
        '**/obj/**',
        '**/target/**',
        // JavaScript/TypeScript
        '**/*.min.js',
        '**/*.bundle.js',
        '**/.next/**',
        '**/.nuxt/**',
        '**/.svelte-kit/**',
        '**/.output/**',
        '**/.turbo/**',
        '**/.cache/**',
        '**/.parcel-cache/**',
        '**/.vite/**',
        '**/.astro/**',
        '**/.docusaurus/**',
        '**/.gatsby/**',
        '**/.webpack/**',
        '**/.nx/**',
        '**/.yarn/cache/**',
        '**/.pnpm-store/**',
        '**/storybook-static/**',
        // React Native / Expo
        '**/.expo/**',
        '**/web-build/**',
        '**/ios/Pods/**',
        '**/ios/build/**',
        '**/android/build/**',
        '**/android/.gradle/**',
        // Python
        '**/__pycache__/**',
        '**/.venv/**',
        '**/venv/**',
        '**/site-packages/**',
        '**/dist-packages/**',
        '**/.pytest_cache/**',
        '**/.mypy_cache/**',
        '**/.ruff_cache/**',
        '**/.tox/**',
        '**/.nox/**',
        '**/*.egg-info/**',
        '**/.eggs/**',
        // Go
        '**/go/pkg/mod/**',
        // Rust
        '**/target/debug/**',
        '**/target/release/**',
        // Java/Kotlin/Gradle
        '**/.gradle/**',
        '**/.m2/**',
        '**/generated-sources/**',
        '**/.kotlin/**',
        // Dart/Flutter
        '**/.dart_tool/**',
        // C#/.NET
        '**/.vs/**',
        '**/.nuget/**',
        '**/artifacts/**',
        '**/publish/**',
        // C/C++
        '**/cmake-build-*/**',
        '**/CMakeFiles/**',
        '**/bazel-*/**',
        '**/vcpkg_installed/**',
        '**/.conan/**',
        '**/Debug/**',
        '**/Release/**',
        '**/x64/**',
        '**/.pio/**', // Platform.io (IoT/embedded build artifacts and library deps)
        // Electron
        '**/release/**',
        '**/*.app/**',
        '**/*.asar',
        // Swift/iOS/Xcode
        '**/DerivedData/**',
        '**/.build/**',
        '**/.swiftpm/**',
        '**/xcuserdata/**',
        '**/Carthage/Build/**',
        '**/SourcePackages/**',
        // Delphi/Pascal
        '**/__history/**',
        '**/__recovery/**',
        '**/*.dcu',
        // PHP
        '**/.composer/**',
        '**/storage/framework/**',
        '**/bootstrap/cache/**',
        // Ruby
        '**/.bundle/**',
        '**/tmp/cache/**',
        '**/public/assets/**',
        '**/public/packs/**',
        '**/.yardoc/**',
        // Testing/Coverage
        '**/coverage/**',
        '**/htmlcov/**',
        '**/.nyc_output/**',
        '**/test-results/**',
        '**/.coverage/**',
        // IDE/Editor
        '**/.idea/**',
        // Logs and temp
        '**/logs/**',
        '**/tmp/**',
        '**/temp/**',
        // Documentation build output
        '**/_build/**',
        '**/docs/_build/**',
        '**/site/**',
    ],
    languages: [],
    frameworks: [],
    maxFileSize: 1024 * 1024, // 1MB
    extractDocstrings: true,
    trackCallSites: true,
};
//# sourceMappingURL=types.js.map