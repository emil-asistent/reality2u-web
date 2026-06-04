<?php

class Import
{

    private $username = null;
    private $password = null;
    private $url = null;
    private $auth_token = null;

    public function __construct($username, $password, $url)
    {
        $this->username = $username;
        $this->password = $password;
        $this->url = $url;
    }

    public function login()
    {
        $json = array(
            'username' => $this->username,
            'password' => $this->password
        );

        $curl = curl_init();

        curl_setopt_array($curl, array(
            CURLOPT_URL => $this->url . "api/user/login",
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_CUSTOMREQUEST => "POST",
            CURLOPT_POSTFIELDS => json_encode($json),
            CURLOPT_SSL_VERIFYHOST => false,
            CURLOPT_SSL_VERIFYPEER => false,
            CURLOPT_HTTPHEADER => array(
                "Content-Type: application/json"
            ),
        ));

        $response = curl_exec($curl);

        $curl_info = curl_getinfo($curl);

        if ($curl_info['http_code'] == 200) {
            $result = json_decode($response, true);

            $this->auth_token = $result['authToken'];

            return true;
        }

        return false;
    }

    public function logout()
    {
        $curl = curl_init();

        curl_setopt_array($curl, array(
            CURLOPT_URL => $this->url . "api/user/logout",
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_CUSTOMREQUEST => "GET",
            CURLOPT_SSL_VERIFYHOST => false,
            CURLOPT_SSL_VERIFYPEER => false,
            CURLOPT_HTTPHEADER => array(
                "Authorization: Bearer " . $this->auth_token
            ),
        ));

        $response = curl_exec($curl);

        curl_close($curl);
    }

    public function getOffers($limit = 10)
    {
        $json = array(
            'limit' => (int)$limit
        );

        $curl = curl_init();

        curl_setopt_array($curl, array(
            CURLOPT_URL => $this->url . "api/offers",
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_CUSTOMREQUEST => "GET",
            CURLOPT_SSL_VERIFYHOST => false,
            CURLOPT_SSL_VERIFYPEER => false,
            CURLOPT_POSTFIELDS => json_encode($json),
            CURLOPT_HTTPHEADER => array(
                "Authorization: Bearer " . $this->auth_token,
                "Content-Type: text/plain",
            ),
        ));

        $response = curl_exec($curl);

        $curl_info = curl_getinfo($curl);

        curl_close($curl);

        $decode = json_decode($response, true);

        return isset($decode['offers']) ? $decode['offers'] : array();
    }

    public function getBrokers($limit = 10)
    {
        $json = array(
            'limit' => (int)$limit
        );

        $curl = curl_init();

        curl_setopt_array($curl, array(
            CURLOPT_URL => $this->url . "api/brokers",
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_CUSTOMREQUEST => "GET",
            CURLOPT_SSL_VERIFYHOST => false,
            CURLOPT_SSL_VERIFYPEER => false,
            CURLOPT_POSTFIELDS => json_encode($json),
            CURLOPT_HTTPHEADER => array(
                "Authorization: Bearer " . $this->auth_token,
                "Content-Type: text/plain",
            ),
        ));

        $response = curl_exec($curl);

        $curl_info = curl_getinfo($curl);

        curl_close($curl);

        $decode = json_decode($response, true);

        return isset($decode['brokers']) ? $decode['brokers'] : array();
    }

    public function getBranches($limit = 10)
    {
        $json = array(
            'limit' => (int)$limit
        );

        $curl = curl_init();

        curl_setopt_array($curl, array(
            CURLOPT_URL => $this->url . "api/branches",
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_CUSTOMREQUEST => "GET",
            CURLOPT_SSL_VERIFYHOST => false,
            CURLOPT_SSL_VERIFYPEER => false,
            CURLOPT_POSTFIELDS => json_encode($json),
            CURLOPT_HTTPHEADER => array(
                "Authorization: Bearer " . $this->auth_token,
                "Content-Type: text/plain",
            ),
        ));

        $response = curl_exec($curl);

        $curl_info = curl_getinfo($curl);

        curl_close($curl);

        $decode = json_decode($response, true);

        return isset($decode['branches']) ? $decode['branches'] : array();
    }

    public function confirmOffers($exports_id)
    {
        $this->confirm($exports_id, 'offers');
    }

    public function confirmBrokers($exports_id)
    {
        $this->confirm($exports_id, 'brokers');
    }

    public function confirmBranches($exports_id)
    {
        $this->confirm($exports_id, 'branches');
    }

    public function confirm($exports_id, $type)
    {
        $json = array(
            'exports_id' => $exports_id
        );

        $curl = curl_init();

        curl_setopt_array($curl, array(
            CURLOPT_URL => $this->url . "api/" . $type . "/confirm",
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_CUSTOMREQUEST => "GET",
            CURLOPT_SSL_VERIFYHOST => false,
            CURLOPT_SSL_VERIFYPEER => false,
            CURLOPT_POSTFIELDS => json_encode($json),
            CURLOPT_HTTPHEADER => array(
                "Authorization: Bearer " . $this->auth_token
            ),
        ));

        $response = curl_exec($curl);

        curl_close($curl);
    }

    public function getFileOffer($file)
    {
        return $this->getFile($file, 'offers');
    }

    public function getFileBranch($file)
    {
        return $this->getFile($file, 'branches');
    }

    public function getFileBroker($file)
    {
        return $this->getFile($file, 'brokers');
    }

    public function getFile($file, $type)
    {
        $json = array(
            'file' => $file
        );

        $curl = curl_init();

        curl_setopt_array($curl, array(
            CURLOPT_URL => $this->url . "api/" . $type . "get-file",
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_FOLLOWLOCATION => true,
            CURLOPT_CUSTOMREQUEST => "POST",
            CURLOPT_SSL_VERIFYHOST => false,
            CURLOPT_SSL_VERIFYPEER => false,
            CURLOPT_POSTFIELDS => json_encode($json),
            CURLOPT_HTTPHEADER => array(
                "Authorization: Bearer " . $this->auth_token
            ),
        ));

        $response = curl_exec($curl);

        curl_close($curl);

        return $response;
    }

}
