<?php

//exit('ACCESS DENIED');
//nacteme knihovnu pro import
include ('class.import.php');

//vytvorime slozku pro stahovani souboru
if(!file_exists(__DIR__ . '/files')){
    mkdir(__DIR__ . '/files', 0777);
}

$import = new Import('login', 'pass', 'url');

//prihlasime se k API
$result = $import->login();

//MAKLERI
$brokers = $import->getBrokers();
$import->confirmBrokers(array_column($brokers, 'export_id'));

echo "<pre>" . print_r('Makleri',true) . "</pre>";
echo "<pre>" . print_r($brokers,true) . "</pre>";

//POBOCKY
$branches = $import->getBranches();
$import->confirmBranches(array_column($branches, 'export_id'));

echo "<pre>" . print_r('Pobocky',true) . "</pre>";
echo "<pre>" . print_r($branches,true) . "</pre>";

//NABIDKY
$offers = $import->getOffers();
$import->confirmBranches(array_column($offers, 'export_id'));

echo "<pre>" . print_r('Nabidky',true) . "</pre>";
echo "<pre>" . print_r($offers,true) . "</pre>";

//nabidky projdeme
foreach($offers as $offer){

    //v pripade ze jsou fotky tak projdeme
    if(!empty($offer['photos'])){

        //fotografie projdeme
        foreach($offer['photos'] as $file){
            $file = str_replace('---', '/', $file);

            $pathinfo = pathinfo($file);

            //stahneme soubor, dostaneme obsah souboru
            $data = $import->getFile($file);

            //soubor ulozime
            file_put_contents(__DIR__ . '/files/' . $pathinfo['basename'], $data);
        }
    }
}

//odhlasime se
$import->logout();


exit('KONEC TESTU');