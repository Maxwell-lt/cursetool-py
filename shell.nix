with import <nixpkgs> {};
let
  pythonEnv = python38.withPackages (ps: [
    ps.pylint
    ps.jedi
  ]);
in mkShell {
  buildInputs = [
    pythonEnv
  ];
}
