"""Prepare course package sets with maintained ecosystem commands."""

import json
import shlex
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.sax.saxutils import escape

from leornian.modules.execution.environment_recipes import recipe


def go_manifest(course):
    dependencies = "\n".join(f"\t{item.name} {item.version}" for item in course.dependencies)
    return f"module learner.local/project\n\ngo 1.26\n\nrequire (\n{dependencies}\n)\n"


def build_context(course, base_image, node_image=None):
    """All executable build instructions are application-owned."""
    if course.build == "http" and not course.dependencies:
        return {"Dockerfile": f"FROM {base_image}\n"}
    files = {}
    dockerfile = []
    if course.build == "vite":
        dockerfile += [
            f"FROM {node_image} AS node_tools",
            "RUN mkdir -p /opt/node-tools && "
            'cp "$(command -v node)" /opt/node-tools/node && '
            'npm_cli="$(readlink -f "$(command -v npm)")" && '
            'cp -r "${npm_cli%/bin/npm-cli.js}" /opt/node-tools/npm',
        ]
    dockerfile.append(f"FROM {base_image}")
    if course.build == "vite":
        dockerfile += [
            "COPY --from=node_tools /opt/node-tools /opt/node-tools",
            "RUN ln -s /opt/node-tools/node /usr/local/bin/node && "
            "ln -s /opt/node-tools/npm/bin/npm-cli.js /usr/local/bin/npm",
        ]
        if course.language == "typescript":
            dockerfile += [
                "COPY --from=node_tools /opt/leornian/node_modules /opt/leornian/node_modules",
                'ENV PATH="/opt/leornian/node_modules/.bin:${PATH}"',
            ]
    if course.language == "python":
        files["requirements.txt"] = "\n".join(
            f"{item.name}=={item.version}" for item in course.dependencies
        ) + "\n"
        dockerfile += [
            "COPY requirements.txt /opt/leornian/course/requirements.txt",
            "RUN python -m pip --isolated install --index-url https://pypi.org/simple "
            "--only-binary=:all: --no-cache-dir --disable-pip-version-check "
            "-r /opt/leornian/course/requirements.txt",
        ]
    elif course.language in {"javascript", "typescript"}:
        files["package.json"] = json.dumps({
            "private": True,
            "dependencies": {item.name: item.version for item in course.dependencies},
        })
        dockerfile += [
            "COPY package.json /opt/leornian/course/package.json",
            "RUN npm --registry=https://registry.npmjs.org install --ignore-scripts "
            "--no-audit --no-fund --prefix /opt/leornian/course",
        ]
        if course.build == "vite":
            names = {item.name for item in course.dependencies}
            plugins = [
                name for name in ("@vitejs/plugin-vue", "@vitejs/plugin-react") if name in names
            ]
            files["build.mjs"] = (
                "import {build} from 'vite';\n"
                f"const plugins = await Promise.all({json.dumps(plugins)}"
                ".map(async name => (await import(name)).default()));\n"
                "await build({configFile:false,root:'/workspace',base:'./',"
                "cacheDir:'/tmp/vite-cache',plugins,"
                "build:{outDir:'/build',emptyOutDir:true,reportCompressedSize:false,"
                "rollupOptions:{maxParallelFileOps:32}}});\n"
            )
            dockerfile.append("COPY build.mjs /opt/leornian/course/build.mjs")
    elif course.language == "java":
        dependencies = []
        for item in course.dependencies:
            group, artifact = item.name.split(":")
            dependencies.append(
                "<dependency><groupId>" + escape(group) + "</groupId><artifactId>"
                + escape(artifact) + "</artifactId><version>" + escape(item.version)
                + "</version></dependency>"
            )
        files["pom.xml"] = (
            '<project xmlns="http://maven.apache.org/POM/4.0.0">'
            "<modelVersion>4.0.0</modelVersion><groupId>learner.local</groupId>"
            "<artifactId>course</artifactId><version>1.0.0</version><dependencies>"
            + "".join(dependencies) + "</dependencies></project>"
        )
        files["settings.xml"] = (
            '<settings xmlns="http://maven.apache.org/SETTINGS/1.0.0"><mirrors><mirror>'
            "<id>course-central</id><mirrorOf>*</mirrorOf>"
            "<url>https://repo.maven.apache.org/maven2</url></mirror></mirrors></settings>"
        )
        dockerfile += [
            "RUN apt-get update && apt-get install -y --no-install-recommends maven "
            "&& rm -rf /var/lib/apt/lists/*",
            "COPY pom.xml /opt/leornian/course/pom.xml",
            "COPY settings.xml /opt/leornian/course/settings.xml",
            "RUN mvn -B -q -s /opt/leornian/course/settings.xml "
            "-f /opt/leornian/course/pom.xml "
            "org.apache.maven.plugins:maven-dependency-plugin:3.8.1:copy-dependencies "
            "-DoutputDirectory=/opt/leornian/course/lib",
        ]
    elif course.language == "go":
        files["go.mod"] = go_manifest(course)
        dockerfile += [
            "COPY go.mod /opt/leornian/course/go.mod",
            "ENV GOMODCACHE=/opt/leornian/go-mod GOTOOLCHAIN=local",
            "RUN cd /opt/leornian/course && GOTOOLCHAIN=local "
            "GOPROXY=https://proxy.golang.org GOSUMDB=sum.golang.org "
            "GOMODCACHE=/opt/leornian/go-mod go mod download all "
            "&& chmod -R a+rX /opt/leornian",
        ]
    else:
        references = "".join(
            f'<PackageReference Include="{escape(item.name)}" Version="{escape(item.version)}" />'
            for item in course.dependencies
        )
        files["Project.csproj"] = (
            '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType>'
            "<TargetFramework>net10.0</TargetFramework><AssemblyName>LearnerProgram</AssemblyName>"
            "<EnableDefaultCompileItems>false</EnableDefaultCompileItems>"
            "<EnableNETAnalyzers>false</EnableNETAnalyzers><ImplicitUsings>enable</ImplicitUsings>"
            "<Nullable>enable</Nullable><UseAppHost>false</UseAppHost></PropertyGroup>"
            '<ItemGroup><Compile Include="/workspace/**/*.cs" />' + references
            + "</ItemGroup></Project>"
        )
        dockerfile += [
            "COPY Project.csproj /opt/leornian/template/Project.csproj",
            "ENV NUGET_PACKAGES=/opt/leornian/nuget",
            "RUN dotnet restore /opt/leornian/template/Project.csproj "
            "--source https://api.nuget.org/v3/index.json --use-lock-file "
            "&& chmod -R a+rX /opt/leornian",
        ]
    files["Dockerfile"] = "\n".join(dockerfile) + "\n"
    return files


def verify_dependencies(installer, course, image, should_continue):
    packages = [item.model_dump(mode="json") for item in course.dependencies]
    if not packages:
        return {}
    if course.language == "python":
        command = [
            "python", "-I", "-B", "-c",
            "import importlib.metadata as m,json;"
            f"packages={packages!r};"
            "print(json.dumps({p['name']:m.version(p['name']) for p in packages}))",
        ]
        found = json.loads(installer._run(image, command, should_continue=should_continue))
    elif course.language in {"javascript", "typescript"}:
        command = [
            "node", "-e",
            "const fs=require('node:fs');"
            f"const packages={json.dumps(packages)};"
            "console.log(JSON.stringify(Object.fromEntries(packages.map(p=>[p.name,"
            "JSON.parse(fs.readFileSync('/opt/leornian/course/node_modules/'"
            "+p.name+'/package.json','utf8')).version]))))",
        ]
        found = json.loads(installer._run(image, command, should_continue=should_continue))
    elif course.language == "go":
        text = installer._run(
            image, [
                "sh", "-ceu", "cd /opt/leornian/course; GOTOOLCHAIN=local "
                "GOPROXY=off GOSUMDB=off GOMODCACHE=/opt/leornian/go-mod go list -m all",
            ], should_continue=should_continue,
        )
        found = dict(line.split()[:2] for line in text.splitlines() if len(line.split()) >= 2)
    else:
        if course.language == "java":
            paths = [
                f"/opt/leornian/course/lib/{item.name.split(':')[1]}-{item.version}.jar"
                for item in course.dependencies
            ]
            tests = ["test -f " + shlex.quote(path) for path in paths]
        else:
            tests = [
                "test -d " + shlex.quote(
                    f"/opt/leornian/nuget/{item.name.lower()}/{item.version.lower()}"
                )
                for item in course.dependencies
            ]
        installer._run(
            image, ["sh", "-ceu", " && ".join(tests)], should_continue=should_continue,
        )
        found = {item.name: item.version for item in course.dependencies}
    if any(found.get(item.name) != item.version for item in course.dependencies):
        raise RuntimeError("Resolved course package versions differ from the approved requirement.")
    return {item.name: found[item.name] for item in course.dependencies}


def prepare_course(installer, maintained, progress, should_continue):
    course = maintained.requirement.course_environment
    baseline = recipe(f"{course.language}-standard.v1")
    base = installer.prepare(
        {"requirement": baseline.requirement.model_dump(mode="json")}, progress, should_continue,
    )
    images = {"base": base["image_id"]}
    node_image = None
    verification_recipe = baseline
    if course.build == "vite":
        node_image = base["image_id"]
        browser_recipe = recipe("html-css-browser.v1")
        browser = installer.prepare(
            {"requirement": browser_recipe.requirement.model_dump(mode="json")},
            progress, should_continue,
        )
        images["browser"] = browser["image_id"]
        verification_recipe = browser_recipe
    if course.build == "http":
        client = installer.prepare(
            {"requirement": recipe("python-standard.v1").requirement.model_dump(mode="json")},
            progress, should_continue,
        )
        images["http_client"] = client["image_id"]
        if course.database in {"postgresql", "mysql"}:
            database = installer.prepare(
                {"requirement": recipe(
                    f"{course.database}-query.v1",
                ).requirement.model_dump(mode="json")},
                progress, should_continue,
            )
            images["database"] = database["image_ids"]["server"]
    cached = installer.cache["recipes"].get(maintained.requirement.recipe_id)
    if cached and cached["verification"].get("course_builder_revision") == 1 and all(
        installer.image(image) == image for image in cached["image_ids"].values()
    ):
        images = dict(cached["image_ids"])
    else:
        if not progress("building"):
            raise RuntimeError("Course installation is no longer authorized.")
        def local_base(image):
            tag = "leornian-course-base:" + image.split(":")[1][:24]
            installer.operation(["tag", image, tag], progress, "building", timeout=15)
            return tag

        base_reference = local_base(images.get("browser", images["base"]))
        node_reference = local_base(node_image) if node_image else None
        with TemporaryDirectory(prefix="course-build-", dir=installer.directory) as directory:
            for name, content in build_context(
                course, base_reference, node_reference,
            ).items():
                (Path(directory) / name).write_text(content, encoding="utf-8")
            tag = "leornian-env:" + maintained.requirement.recipe_id
            installer.operation([
                "build", "--pull=false", "--network=default", "--tag", tag, directory,
            ], progress, "building")
            images["runtime"] = installer.image(tag)
            if not images["runtime"]:
                raise RuntimeError("The built course dependency image is unavailable.")
    if not progress("verifying"):
        raise RuntimeError("Course verification is no longer authorized.")
    version, toolchains = installer.verify(verification_recipe, images, should_continue)
    dependencies = verify_dependencies(installer, course, images["runtime"], should_continue)
    if course.build == "vite":
        toolchains["node"] = installer._run(
            images["runtime"], ["node", "-p", "process.versions.node"],
            should_continue=should_continue,
        ).strip()
        toolchains["vite"] = dependencies["vite"]
        if course.language == "typescript":
            toolchains["typescript"] = installer._run(
                images["runtime"], ["tsc", "--version"], should_continue=should_continue,
            ).split()[-1]
    result = {
        "outcome": "ready", "runtime_version": version, "image_id": images["runtime"],
        "image_ids": images, "toolchains": toolchains,
        "verification": {
            "isolated": True, "smoke": True, "learner_network": "none",
            "recipe_id": maintained.requirement.recipe_id, "recipe_revision": 1,
            "course_builder_revision": 1,
            "dependency_lock": maintained.requirement.dependency_lock,
            "course_environment": course.model_dump(mode="json"),
            "installed_dependencies": dependencies,
        },
    }
    installer.cache["recipes"][maintained.requirement.recipe_id] = result
    installer.save()
    return result
