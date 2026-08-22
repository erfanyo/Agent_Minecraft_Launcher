plugins {
    id("net.minecraftforge.gradle") version "6.0"
}

dependencies {
    implementation(project(":common"))
    minecraft("net.minecraftforge:forge:1.21.1-52.1.16")
}

minecraft {
    mappings channel = "official", version = "1.21.1"
}
