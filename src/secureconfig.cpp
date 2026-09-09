#include "secureconfig.h"

#include <openssl/crypto.h>
#include <openssl/rand.h>
#include <cerrno>
#include <cstring>

#ifdef WIN32
#include <windows.h>
#include <sddl.h>
#else
#include <fcntl.h>
#include <unistd.h>
#endif

bool CreateRPCConfig(const std::string& path, std::string& error)
{
    error.clear();
    unsigned char random[48];
    if (RAND_bytes(random, sizeof(random)) != 1) {
        OPENSSL_cleanse(random, sizeof(random));
        error = "Cannot generate secure RPC credentials; configuration was not created.";
        return false;
    }

    static const char hex[] = "0123456789abcdef";
    std::string credentials;
    for (size_t i = 0; i < sizeof(random); ++i) {
        credentials += hex[random[i] >> 4];
        credentials += hex[random[i] & 15];
    }
    OPENSSL_cleanse(random, sizeof(random));
    std::string config = "rpcuser=user" + credentials.substr(0, 32)
        + "\nrpcpassword=" + credentials.substr(32)
        + "\nrpcbind=127.0.0.1\n# Enable staking (0=off, 1=on)\nstaking=1\n";
    OPENSSL_cleanse(&credentials[0], credentials.size());

    bool created = false;
    bool success = false;
#ifdef WIN32
    // A protected DACL granting access to the file owner, without inherited
    // permissions. OWNER RIGHTS is supported on Windows Vista and later.
    PSECURITY_DESCRIPTOR descriptor = NULL;
    if (ConvertStringSecurityDescriptorToSecurityDescriptorA(
            "D:P(A;;FA;;;OW)", SDDL_REVISION_1, &descriptor, NULL)) {
        SECURITY_ATTRIBUTES attributes = {sizeof(SECURITY_ATTRIBUTES), descriptor, FALSE};
        HANDLE file = CreateFileA(path.c_str(), GENERIC_WRITE, 0, &attributes,
                                 CREATE_NEW, FILE_ATTRIBUTE_NORMAL, NULL);
        LocalFree(descriptor);
        if (file != INVALID_HANDLE_VALUE) {
            created = true;
            DWORD written = 0;
            success = WriteFile(file, config.data(), static_cast<DWORD>(config.size()),
                                &written, NULL) && written == config.size();
            if (success)
                success = FlushFileBuffers(file) != 0;
            if (!CloseHandle(file))
                success = false;
        }
    }
    if (!success) {
        error = "Cannot securely create RPC configuration; check the path and permissions.";
        if (created)
            DeleteFileA(path.c_str());
    }
#else
    int file = open(path.c_str(), O_WRONLY | O_CREAT | O_EXCL, 0600);
    if (file >= 0) {
        created = true;
        size_t offset = 0;
        while (offset < config.size()) {
            ssize_t count = write(file, config.data() + offset, config.size() - offset);
            if (count < 0 && errno == EINTR)
                continue;
            if (count <= 0)
                break;
            offset += static_cast<size_t>(count);
        }
        success = offset == config.size() && fsync(file) == 0;
        if (close(file) != 0)
            success = false;
    }
    if (!success) {
        error = "Cannot securely create RPC configuration; check the path and permissions.";
        if (created)
            unlink(path.c_str());
    }
#endif
    OPENSSL_cleanse(&config[0], config.size());
    return success;
}
